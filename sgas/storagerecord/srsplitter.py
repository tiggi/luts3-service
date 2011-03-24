"""
Storage Record splitter to split an storage records XML document (which can
contain one or more storage records) into a list storage records.

Author: Henrik Thostrup Jensen <htj@ndgf.org>
Copyright: NorduNET / Nordic Data Grid Facility (2011)
"""


from xml.etree import cElementTree as ET

from sgas.storagerecord import srelements as sr



class ParseError(Exception):
    """
    Raised when an error occurs during the parsing for splitting up the ur
    elements.
    """


def splitSRDocument(sr_data):

    storage_records = []

    try:
        tree  = ET.fromstring(sr_data)
    except Exception, e:
        raise ParseError("Error parsing storage record data (%s)" % str(e))

    if tree.tag == sr.STORAGE_USAGE_RECORDS:
        for sr_element in tree:
            if not sr_element.tag == sr.STORAGE_USAGE_RECORD:
                raise ParseError("Subelement in StoragUsageeRecords doc not a StorageUsageRecord")
            storage_records.append(sr_element)

    elif tree.tag == sr.STORAGE_USAGE_RECORD:
        storage_records.append(tree)

    else:
        raise ParseError("Top element is not StorageUsageRecords or StorageUsageRecord")

    return storage_records

