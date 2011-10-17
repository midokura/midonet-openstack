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
                         'args': {'label': kwargs.get('label'),
                                  'cidr': kwargs.get('cidr'),
                                  'multi_host': kwargs.get('multi_host'),
                                  'network_size': kwargs.get('network_size'),
                                  'cidr_v6': kwargs.get('cidr_v6'),
                                  'gateway_v6': kwargs.get('gateway_v6'),
                                  'bridge': kwargs.get('bridge'),
                                  'bridge_interface': kwargs.get('bridge_interface'),
                                  'dns1': kwargs.get('dns1'),
                                  'dns2': kwargs.get('dns2'),
                                  'project_id': kwargs.get('project_id')
                                  }})

    def delete_network(self, context, fixed_range):
        return rpc.call(context, FLAGS.network_topic,
                        {'method': 'delete_network',
                         'args': {'fixed_range': fixed_range
                                  }})

    def get_network(self, context, uuid):
        return self.db.network_get_by_uuid(context, uuid)


