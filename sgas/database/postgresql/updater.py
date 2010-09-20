"""
Aggregation table updater.

This module will listen for update notifications and will thereafter update
the aggregation table in PostgreSQL. As this operation can take some time,
the operation cannot be done in insertion, and must hence be done
asyncrhronously and a bit clever.

Originally it was planned to use the NOTIFY/LISTEN functionality in PostgreSQL,
but I could not make it work using adbapi (and it appears other have this
problem as well).

Author: Henrik Thostrup Jensen <htj@ndgf.org>
Copyright: Nordic Data Grid Facility (2010)
"""

import psycopg2

from twisted.python import log
from twisted.internet import defer, reactor
from twisted.application import service



SQL_SERIALIZABLE_TRANSACTION = '''SET TRANSACTION ISOLATION LEVEL SERIALIZABLE'''

AGGREGATE_UPDATE_QUERY = '''SELECT * FROM uraggregated_update ORDER BY insert_time LIMIT 1'''

DELETE_AGGREGATED_UPDATE = '''DELETE FROM uraggregated_update WHERE insert_time = %s AND machine_name = %s'''
DELETE_AGGREGATED_INFO = '''DELETE FROM uraggregated WHERE insert_time = %s AND machine_name = %s'''

# a nice small insert statement
UPDATE_AGGREGATED_INFO = '''
INSERT INTO uraggregated
SELECT
    COALESCE(end_time::DATE, create_time::DATE)                      AS s_execute_time,
    insert_time::DATE                                                AS s_insert_time,
    machine_name                                                     AS s_machine_name,
    COALESCE(global_user_name, machine_name || ':' || local_user_id) AS s_user_identity,
    CASE WHEN vo_issuer LIKE 'file:///%%'
        THEN NULL
        ELSE vo_issuer
    END                                                              AS s_vo_issuer,
    CASE WHEN vo_name is NULL
        THEN COALESCE(machine_name || ':' || project_name)
        ELSE
            CASE WHEN vo_name LIKE '/%%'
                THEN NULL
                ELSE vo_name
            END
    END                                                              AS s_vo_name,
    vo_attributes[1][1]                                              AS s_vo_group,
    vo_attributes[1][2]                                              AS s_vo_role,
    count(*)                                                         AS s_n_jobs,
    SUM(COALESCE(cpu_duration,0))  / 3600.0                          AS s_cputime,
    SUM(COALESCE(wall_duration,0) * COALESCE(processors,1)) / 3600.0 AS s_walltime,
    now()                                                            AS s_generate_time
FROM
    usagerecords
WHERE
    insert_time::date = %s AND machine_name = %s
GROUP BY
    s_execute_time, s_insert_time, s_machine_name, s_user_identity, s_vo_issuer, s_vo_name, s_vo_group, s_vo_role;
'''



class AggregationUpdater(service.Service):

    def __init__(self, pool_proxy):

        self.pool_proxy = pool_proxy

        self.need_update = False
        self.updating    = False
        self.stopping    = False
        self.update_call = None
        self.update_def  = None


    def startService(self):
        service.Service.startService(self)
        # we might have been shutdown while some updates where pending,
        # or some records could have been inserted outside SGAS, so we
        # always schedule an update when starting
        self.scheduleUpdate()
        return defer.succeed(None)


    def stopService(self):
        self.stopping = True
        service.Service.stopService(self)
        if self.update_call is not None:
            self.update_call.cancel()
        if self.update_def is not None:
            return self.update_def
        else:
            return defer.succeed(None)


    def updateNotification(self):
        # the database need to be updated, schedule call
        self.need_update = True
        self.scheduleUpdate()


    def scheduleUpdate(self, delay=20):
        # only schedule call if no other call is planned
        if self.update_call is None:
            log.msg('Scheduling update for aggregated table in %i seconds.' % delay)
            self.update_call = reactor.callLater(delay, self.performUpdate, True)


    def performUpdate(self, remove_call=False):
        if remove_call:
            self.update_call = None
        if self.updating:
            # if an update is running, defer this update to (much) later
            self.scheduleUpdate(delay=120)
            return defer.succeed(None)
        else:
            d = self.update()
            self.update_def = d
            return d

    # -- end scheduling logic

    def _performUpdate(self, txn):
        # This is performed outside the main Twisted thread and runs in a
        # blocking manner # i.e., no deferreds should be used.
        # Furthermore the function is run within a transaction, so if any
        # errors occurs everything is rolled back.

        # FIXME make a pg/plsql function for this, to avoid ping-ponging
        # with the database

        txn.execute(SQL_SERIALIZABLE_TRANSACTION)
        txn.execute(AGGREGATE_UPDATE_QUERY)
        rows = txn.fetchall()
        if not rows:
            return # nothin to do

        assert len(rows) == 1, 'Multiple rows returned for LIMIT 1 query'
        insert_date, machine_name = rows[0]
        insert_date = str(insert_date)

        txn.execute(DELETE_AGGREGATED_INFO, (insert_date, machine_name))
        txn.execute(UPDATE_AGGREGATED_INFO, (insert_date, machine_name))
        txn.execute(DELETE_AGGREGATED_UPDATE, (insert_date, machine_name))
        return insert_date, machine_name


    @defer.inlineCallbacks
    def update(self):
        # will update the parts of the aggregated data table which has been
        # specified to need an update in the update table

        self.updating = True
        self.has_reconnected = False

        try:
            while True:
                try:
                    idmn = yield self.pool_proxy.dbpool.runInteraction(self._performUpdate)
                    if idmn:
                        insert_date, machine_name = idmn
                        log.msg('Aggregation updated: %s / %s' % (insert_date, machine_name))
                    else: # no more updates to perform
                        break
                    if self.stopping:
                        break
                except psycopg2.OperationalError, e:
                    # if the transaction fails due to closed connection, it will cause an interface error
                    # however dbapi will try to rollback, which will wrap/cause OperationalError instead
                    # FIXME in the future the updating should be done in pgplsql function to avoid this
                    if self.has_reconnected:
                        log.msg('Reconnect in update failed, bailing out.')
                        raise
                    else:
                        log.msg('Got OperationalError while attempting update: %s.' % str(e))
                        log.msg('Attempting reconnect.')
                        self.has_reconnected = True
                        self.pool_proxy.reconnect()

        except Exception, e:
            log.err(e)
            raise

        finally:
            self.updating = False


    def rebuild(self):
        # will perform a full rebuild of the data in the aggegration table
        # note that this is can be a fairly heavy operation often taking
        # several minutes (increasing the work_mem parameter can often lower
        # the time required)

        # not quite there yet
        pass

