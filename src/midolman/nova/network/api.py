# vim: tabstop=4 shiftwidth=4 softtabstop=4

"""Handles all requests relating to instances (guest vms)."""

from nova import flags
from nova import rpc
from nova import network

from midolman.nova import flags as mido_flags

FLAGS = flags.FLAGS

class MidoAPI(network.API):

    def create_network(self, context, **kwargs):
        return rpc.call(context, FLAGS.network_topic,
                        {'method': 'create_network',
                         'args': {'label': kwargs['label'],
                                  'cidr': kwargs['cidr'],
                                  'multi_host': kwargs['multi_host'],
                                  'network_size': kwargs['network_size'],
                                  'cidr_v6': kwargs['cidr_v6'],
                                  'gateway_v6': kwargs['gateway_v6'],
                                  'bridge': kwargs['bridge'],
                                  'bridge_interface': kwargs['bridge_interface'],
                                  'dns1': kwargs['dns1'],
                                  'dns2': kwargs['dns2'],
                                  'project_id': kwargs['project_id']
                                  }})

    def delete_network(self, context, fixed_range):
        return rpc.call(context, FLAGS.network_topic,
                        {'method': 'delete_network',
                         'args': {'fixed_range': fixed_range
                                  }})

    def get_network(self, context, uuid):
        return self.db.network_get_by_uuid(context, uuid)


