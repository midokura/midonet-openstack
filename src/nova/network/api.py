# vim: tabstop=4 shiftwidth=4 softtabstop=4

"""Handles all requests relating to instances (guest vms)."""

from nova import exception
from nova import flags
from nova import log as logging
from nova import rpc
from nova import network

class MidoAPI(network.API):

    def create_networks(self, context):
        #return rpc.call("create_network")
        pass

    def get_network(self, context, uuid):
        return self.db.network_get_by_uuid(context, uuid)

    def list_networks(self, context):
       #db.network_get_all()
       pass

