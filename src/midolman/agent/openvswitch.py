# Copyright (C) 2010 Midokura KK
#
# Openvswitch helper for Midolman Net Agent

from midolman import openvswitch

class OvsConnection(object):
    """The Openvswitch DB connection.
    """

    def __init__(self):
        """Create OvsConnection object.
        """
        self._conn_factory = None

    def initialize(self, url, ext_id_key):
        """Create the Openvswitch DB connection.

        Args:
            url: OVS DB url to connect to.
            ext_id_key: External ID key to use for Midonet-specific values..
        """
        self._conn_factory = openvswitch.ServerConnectionFactory(url, ext_id_key)

    def get_connection(self):
        """Get the connection object.

        Returns:
            Openvswitch connection object.
        """
        return self._conn_factory.open_ovsdb_connection()

OvsConn = OvsConnection()

