import nova.network.manager as nova_network_manager
from nova.db import api
import sys


sys.path.insert(0,'/home/tomoe/code/midolman-nova/src/midolman/midonet') 
import client as midonet

#class NetworkManager(manager.SchedulerDependentManager):

class MidonetManager(nova_network_manager.NetworkManager):
#    def __init__(self):
#        print "-------------------Midonet Manager-------"

#    def create_networks(self, context, label, cidr, multi_host, num_networks,
#                        network_size, cidr_v6, gateway_v6, bridge,
#                        bridge_interface, dns1=None, dns2=None, **kwargs):
    def create_networks(self, context, **kwargs):

        print "-------------------Midonet Manager. create_networks-------"
        print "---kwargs", kwargs
#        print '----dir(context)', dir(context)
#        print 'context.auth_token', context.auth_token
#        print label
#        print 'cidr', cidr
#        print 'multi_host', multi_host
#        print 'num_networks', num_networks
#        print 'network_size', network_size
#        print 'cidr_v6', cidr_v6
#        print 'gateway_v6', gateway_v6
#        print 'bridge', bridge
#        print 'bridge_interface', bridge_interface
#        print 'dns1', dns1
#        print 'dns2', dns2
        print '**kwargs', kwargs

        project_id = kwargs['project_id']
        print 'project_id: ', project_id

        #"TODO(tomoe) hard_code token for provider role and router_id. should be stored in config file
        context.auth_token = '2010'
        PROVIDER_ROUTER_ID = '2e180574-6e14-4c03-922f-d811cfe83d68'

        NETWORK_ADDRESS = '10.0.0.0'
        NETWORK_LENGTH = '30'
        PROVIDER_ROUTER_PORT_ADDRESS = '10.0.0.1'
        TENANT_ROUTER_PORT_ADDRESS = '10.0.0.2'

        
        #TODO(tomoe) To check if the user has Provider role
        #if  not MIDONET_PROVIDE_ROLE in  context.roles:
        #   raise error or return some object to caller?

        mc = midonet.MidonetClient(context.auth_token)

        # project_id maps to tenant_id
        tenant_id = project_id

        # create the tenant in midonet and create routers for the tenant
        response, content = mc.create_tenant(tenant_id)
        if kwargs['num_networks'] > 1:
            raise  #TODO
        router_name = kwargs['label']
        response, content= mc.create_router(tenant_id, router_name)
        router_id = response['location'].split('/')[-1]

        print response
        print 'router-id', router_id

        # Create logical port on the provider router
        response, content = mc.create_router_logical_port(router_id, NETWORK_ADDRESS,\
                                       NETWORK_LENGTH, PROVIDER_ROUTER_PORT_ADDRESS,\
                                       peer_id=None)
        provider_port_id = response['location'].split('/')[-1]
        
        # create logical port on the tenant router
        response, content = mc.create_router_logical_port(router_id, NETWORK_ADDRESS,\
                                       NETWORK_LENGTH, TENANT_ROUTER_PORT_ADDRESS,\
                                       peer_id=provider_port_id)

        tenant_port_id = response['location'].split('/')[-1]

        responce, content = mc.update_router_port_peer_id(provider_port_id, tenant_port_id)


        #TODO(tomoe): call super to make nova happy. need to fake bridge_interface
        networks = super(MidonetManager, self).create_networks(context, **kwargs)

        # Hack to put uuid inside database
        api.network_update(context, networks[0].id, {"uuid": router_id})


