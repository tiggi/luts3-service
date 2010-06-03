"""
Implementation of ISGASDatabase interface for PostgreSQL.

Author: Henrik Thostrup Jensen <htj@ndgf.org>
Copyright: Nordic Data Grid Facility (2010)
"""

from pyPgSQL import libpq, PgSQL

from zope.interface import implements

from twisted.python import log
from twisted.internet import defer
from twisted.enterprise import adbapi 

from sgas.database import ISGASDatabase, error, queryparser
from sgas.database.postgresql import urparser, queryengine




class PostgreSQLDatabase:

    implements(ISGASDatabase)

    def __init__(self, connect_info):

        self.dbpool = adbapi.ConnectionPool('pyPgSQL.PgSQL', connect_info)


    @defer.inlineCallbacks
    def insert(self, usagerecord_data, insert_identity=None, insert_hostname=None):
        # inserts usage record
        try:
            insert_stms = urparser.usageRecordsToInsertStatements(usagerecord_data,
                                                                  insert_identity=insert_identity,
                                                                  insert_hostname=insert_hostname)
            result = yield self.dbpool.runQuery(insert_stms)
            # getting results from functions is a bit strange...
            id_dict = dict( [ r[0][1:-1].rsplit(',',2) for r in result ] )
            for k,v in id_dict.items():
                if v.isdigit():
                    id_dict[k] = int(v)
            defer.returnValue(id_dict)
        except libpq.DatabaseError, e:
            #if 'Connection refused' in e.message:
            if 'Connection refused' in str(e):
                raise error.DatabaseUnavailableError(str(e))
            raise # re-raise current exception
        except Exception, e:
            print e
            log.msg('Unexpected database error')
            log.error(r)
            raise


    @defer.inlineCallbacks
    def query(self, selects, filters=None, groups=None, orders=None):

        def buildValue(value):
            if type(value) in (unicode, str, int, float, bool):
                return value
            if isinstance(value, PgSQL.PgNumeric):
                if value.getPrecision() == 0:
                    return int(value)
                else:
                    return float(value)
            # bad catch-all
            return str(value)

        q = queryparser.QueryParser(selects, filters, groups, orders)

        query_stm = queryengine.buildQuery(q)

        query_result = yield self.dbpool.runQuery(query_stm)

        results = []
        for row in query_result:
            results.append( [ buildValue(e) for e in row ] )

        defer.returnValue(results)

