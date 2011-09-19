from midolman.midonet import client as midonet
from nova.network.manager import NetworkManager 
from nova.db import api
from nova import flags

FLAGS = flags.FLAGS
flags.DEFINE_string('mido_provider_router_id',
                    'bb150806-f7cf-4aa3-9438-dccb58c86cc6',
                    'UUID of the provider router in MidoNet')
flags.DEFINE_string('mido_link_port_network_address',
                    '10.0.0.0',
                    'Network address for MidoNet logical ports')
flags.DEFINE_integer('mido_link_port_network_len', 30,
                     'Network address length for MidoNet logical ports')
flags.DEFINE_string('mido_link_local_port_network_address',
                    '10.0.0.1',
                    'Network address for MidoNet local logical ports')
flags.DEFINE_string('mido_link_peer_port_network_address',
                    '10.0.0.2',
                    'Network address for MidoNet logical port peer')


def _extract_id_from_header_location(response):
    return response['location'].split('/')[-1]

class MidonetManager(NetworkManager):

    def create_network(self, context, label, cidr, multi_host,
                       network_size, cidr_v6, gateway_v6, bridge,
                       bridge_interface, dns1=None, dns2=None, **kwargs):
        print "-------------------Midonet Manager. create_networks-------"
        #PROVIDER_ROUTER_ID = '2e180574-6e14-4c03-922f-d811cfe83d68'

        mc = midonet.MidonetClient(context.auth_token)
        tenant_id = kwargs['project_id']
        router_name = label

        print 'context.auth_token', context.auth_token
        print 'tenant_id', tenant_id 
        print 'router_name', router_name 

        # Create the tenant.  Swallow any error here.(YUCK!)
        response, content = mc.create_tenant(tenant_id)

        # Create a router for this tenant.
        response, content= mc.create_router(tenant_id, router_name)
        router_id = _extract_id_from_header_location(response)
        print 'router_id', router_id 

        # Link this router to the provider router via logical ports.
        response, content= mc.link_router(router_id,
                                          FLAGS.mido_link_port_network_address,
                                          FLAGS.mido_link_port_network_len,
                                          FLAGS.mido_link_local_port_network_address,
                                          FLAGS.mido_link_peer_port_network_address,
                                          FLAGS.mido_provider_router_id)
        print 'created tenant router' 

        # Create a network in Nova and link it with the tenant router in MidoNet. 
        networks = super(MidonetManager, self).create_networks(context, label, cidr, multi_host, 1,
                        network_size, cidr_v6, gateway_v6, bridge,
                        bridge_interface, dns1, dns2, **kwargs)
        print 'created network' 

        if networks is None or len(networks) == 0:
            return None
        network = networks[0]

        # Hack to put uuid inside database
        api.network_update(context, network.id, {"uuid": router_id})
        return network

