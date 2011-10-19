# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (C) 2011 Midokura KK
#
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

from midolman.midonet import client as midonet
from nova import db
from nova import log as logging
from nova import utils
from nova.network import manager
from nova.network.manager import FlatManager 
from nova.network.manager import RPCAllocateFixedIP 
from nova.network.manager import FloatingIP 
from nova import flags
from nova import exception

FLAGS = flags.FLAGS
flags.DEFINE_string('mido_api_host', '127.0.0.1', 'API host of MidoNet')
flags.DEFINE_integer('mido_api_port', 8080, 'Port of the MidoNet API server')
flags.DEFINE_string('mido_api_app', 'midolmanj-mgmt',
                    'App name of the API server.')
flags.DEFINE_string('mido_ipam_lib', 'nova.network.quantum.nova_ipam_lib',
                    "Indicates underlying IP address management library")
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
flags.DEFINE_string('mido_provider_router_id',
                    '3cc61b4a-5845-4c9a-bd5c-2f7851b72f66',
                    'UUID of the provider router in MidoNet')
flags.DEFINE_string('mido_admin_token', '999888777666',
                    'Keystone Admin token to use to access MidoNet')
LOG = logging.getLogger('midolman.nova.network.manager')


class MidonetManager(FloatingIP, FlatManager):

    def __init__(self, ipam_lib=None, *args, **kwargs):
        if not ipam_lib:
            ipam_lib = FLAGS.mido_ipam_lib
        self.ipam = utils.import_object(ipam_lib).get_ipam_lib(self)
        super(MidonetManager, self).__init__(*args, **kwargs)

    def create_networks(self, context, label, cidr, multi_host, num_networks,
                        network_size, cidr_v6, gateway_v6, bridge,
                        bridge_interface, dns1=None, dns2=None, uuid=None,
                        project_id=None, priority=0):
        if num_networks != 1:
            raise Exception(_("MidoNetManager requires that only one"
                              " network is created per call"))

        tenant_id = project_id
        if tenant_id is None:
            raise Exception(_("MidoNetManager requires that a tenant is"
                              " specified per call"))

        conn = midonet.MidonetClient(FLAGS.mido_api_host, FLAGS.mido_api_port,
                                     FLAGS.mido_api_app,
                                     token=context.auth_token)

        # Create the tenant.
        try:
            conn.create_tenant(tenant_id)
        except:
            # Swallow any error here.(YUCK!)
            pass

        net_id = uuid
        if net_id:
            if not conn.tenant_router_exists(tenant_id, net_id):
                    raise Exception(_("Unable to find existing Midonet " \
                        " network for tenant '%(tenant_id)s' with "
                        "net-id '%(net_id)s'" % locals()))
        else:
            # otherwise, create network
            net_id = conn.create_router(tenant_id, label)

            # Link this router to the provider router via logical ports.
            _provider_port, tenant_port = conn.link_router(net_id,
                FLAGS.mido_link_port_network_address,
                FLAGS.mido_link_port_network_len,
                FLAGS.mido_link_local_port_network_address,
                FLAGS.mido_link_peer_port_network_address,
                FLAGS.mido_provider_router_id)

            conn.create_route(net_id, '0.0.0.0', 0, 'Normal', '0.0.0.0',
                                   0, tenant_port, None, 100)

        self.ipam.create_subnet(context, label, tenant_id, net_id, priority,
                                cidr, gateway_v6, cidr_v6, dns1, dns2)

    def delete_network(self, context, fixed_range):
        tenant_id = context.project_id
        net_id = self.ipam.get_network_id_by_cidr(
            context, fixed_range, tenant_id)
        self.ipam.delete_subnets_by_net_id(context, net_id, tenant_id)
        conn = midonet.MidonetClient(FLAGS.mido_api_host, FLAGS.mido_api_port,
                                     FLAGS.mido_api_app,
                                     token=context.auth_token)
        try:
           conn.delete_router(net_id)
        except Exception, ex:
           LOG.error("Failed to create router. %s" % ex) 

    def allocate_for_instance(self, context, **kwargs):
        instance_id = kwargs.pop('instance_id')
        instance_type_id = kwargs['instance_type_id']
        host = kwargs.pop('host')
        tenant_id = kwargs.pop('project_id')
        LOG.debug(_("network allocations for instance %s"), instance_id)

        requested_networks = kwargs.get('requested_networks')

        if requested_networks:
            net_proj_pairs = [(net_id, tenant_id) \
                for (net_id, _i) in requested_networks]
        else:
            net_proj_pairs = self.ipam.get_project_and_global_net_ids(context,
                tenant_id)

        conn = midonet.MidonetClient(FLAGS.mido_api_host, FLAGS.mido_api_port,
                                     FLAGS.mido_api_app,
                                     token=context.auth_token)

        # Create a port via quantum and attach the vif
        for (net_id, tenant_id) in net_proj_pairs:

            admin_context = context.elevated()
            network_ref = db.network_get_by_uuid(admin_context, net_id)

            vif_rec = manager.FlatManager.add_virtual_interface(self,
                context, instance_id, network_ref['id'])

            # Assign an IP address
            self.ipam.allocate_fixed_ip(context, tenant_id, net_id, vif_rec)

            # Get the IP for this vif
            ip = db.fixed_ip_get_by_virtual_interface(vif_rec['id'])[0]

            # talk to MidoNet API to create and attach port.
            network_address, network_len = network_ref['cidr'].split('/')
            gateway = network_ref['gateway']
            port_id = conn.create_router_port(net_id, network_address,
                                              network_len, gateway,
                                              ip.address, 32)
            conn.create_route(net_id, '0.0.0.0', 0, 'Normal',
                              ip.address, 32, port_id, None, 100)
            conn.create_vif(vif_rec['uuid'], port_id)

        return self.get_instance_nw_info(context, instance_id,
                                         instance_type_id, host)


    def get_instance_nw_info(self, context, instance_id,
                             instance_type_id, host):
        network_info = []
        instance = db.instance_get(context, instance_id)
        project_id = instance.project_id

        admin_context = context.elevated()
        vifs = db.virtual_interface_get_by_instance(admin_context,
                                                    instance_id)

        conn = midonet.MidonetClient(FLAGS.mido_api_host, FLAGS.mido_api_port,
                                     FLAGS.mido_api_app,
                                     token=FLAGS.mido_admin_token)
        for vif in vifs:
            tenant_id = project_id
            try:
                net_id, port_id = conn.get_vif_device_and_port(vif['uuid'])
            except Exception, ex:
                # Continue on to try get network info for other VIFs.
                LOG.error("Could not get network data for VIF %s" % vif['uuid'])
                continue
                                                     
            (v4_subnet, v6_subnet) = self.ipam.get_subnets_by_net_id(context,
                                                                     tenant_id,
                                                                     net_id)
            v4_ips = self.ipam.get_v4_ips_by_interface(context,
                                                       net_id, vif['uuid'],
                                                       project_id=tenant_id)
            v6_ips = self.ipam.get_v6_ips_by_interface(context, net_id,
                                                       vif['uuid'],
                                                       project_id=tenant_id)

            def ip_dict(ip, subnet):
                return {
                    "ip": ip,
                    "netmask": subnet["netmask"],
                    "enabled": "1"}

            network_dict = {
                'cidr': v4_subnet['cidr'],
                'injected': True,
                'multi_host': False}

            info = {
                'gateway': v4_subnet['gateway'],
                'dhcp_server': v4_subnet['gateway'],
                'broadcast': v4_subnet['broadcast'],
                'mac': vif['address'],
                'vif_uuid': vif['uuid'],
                'dns': [],
                'ips': [ip_dict(ip, v4_subnet) for ip in v4_ips],
                'port_id': port_id}

            if v6_subnet:
                if v6_subnet['cidr']:
                    network_dict['cidr_v6'] = v6_subnet['cidr']
                    info['ip6s'] = [ip_dict(ip, v6_subnet) for ip in v6_ips]

                if v6_subnet['gateway']:
                    info['gateway6'] = v6_subnet['gateway']

            dns_dict = {}
            for s in [v4_subnet, v6_subnet]:
                for k in ['dns1', 'dns2']:
                    if s and s[k]:
                        dns_dict[s[k]] = None
            info['dns'] = [d for d in dns_dict.keys()]

            network_info.append((network_dict, info))
        return network_info

    def deallocate_for_instance(self, context, **kwargs):
        instance_id = kwargs.get('instance_id')
        tenant_id = kwargs.pop('project_id', None)

        admin_context = context.elevated()
        vifs = db.virtual_interface_get_by_instance(admin_context,
                                                    instance_id)
        conn = midonet.MidonetClient(FLAGS.mido_api_host, FLAGS.mido_api_port,
                                     FLAGS.mido_api_app,
                                     token=context.auth_token)
        for vif_ref in vifs:
            interface_id = vif_ref['uuid']
            try:
                net_id, port_id = conn.get_vif_device_and_port(interface_id)
            except Exception, ex:
                # Continue on to try get network info for other VIFs.
                LOG.error("Could not get network data for VIF %s" % interface_id)
                continue
                                                     
            conn.delete_port(port_id)

            self.ipam.deallocate_ips_by_vif(context, tenant_id,
                                            net_id, vif_ref)

        try:
            db.virtual_interface_delete_by_instance(admin_context,
                                                    instance_id)
        except exception.InstanceNotFound:
            LOG.error(_("Attempted to deallocate non-existent instance: %s" %
                        (instance_id)))

    def associate_floating_ip(self, context, floating_address, fixed_address):
        """Associates a floating ip to a fixed ip."""
        floating_ip = db.floating_ip_get_by_address(context,
                                                         floating_address)
        if floating_ip['fixed_ip']:
            raise exception.FloatingIpAlreadyInUse(
                            address=floating_ip['address'],
                            fixed_ip=floating_ip['fixed_ip']['address'])

        db.floating_ip_fixed_ip_associate(context,
                                          floating_address,
                                          fixed_address,
                                          self.host)

        conn = midonet.MidonetClient(FLAGS.mido_api_host, FLAGS.mido_api_port,
                                     FLAGS.mido_api_app,
                                     token=context.auth_token)

        # Determine the network that the fixed IP belongs to.
        floating_ip = db.floating_ip_get_by_address(context,
                                                    floating_address)
        network_id = floating_ip['fixed_ip']['network_id']
        tenant_router_id = db.network_get(context, network_id)['uuid']

        LOG.debug("  floating_ip: %s", floating_ip)
        LOG.debug("  tenant_router_id: %s", tenant_router_id)

        # Get the logical router port UUID that connects the provider router
        # this tenant router.
        response, content = conn.get_peer_router_detail(tenant_router_id,
                                               FLAGS.mido_provider_router_id)
        provider_router_port_id = content['peerPortId']  
        LOG.debug("  provider_router_port_id: %s", provider_router_port_id)

        # Add a DNAT rule 
        response, content = conn.create_dnat_rule(
             tenant_router_id, floating_address,
             floating_ip['fixed_ip']['address'])

        # Add a SNAT rule 
        response, content = conn.create_snat_rule(
             tenant_router_id, floating_address,
             floating_ip['fixed_ip']['address'])
                                                
        # Set up a route in the provider router.
        response, content = conn.create_route(FLAGS.mido_provider_router_id,
                                            '0.0.0.0', 0, 'Normal',
                                            floating_address, 32, 
                                            provider_router_port_id, None, 100)

    def disassociate_floating_ip(self, context, floating_address):
        """Disassociates a floating ip."""

        # Get the logical router port UUID that connects the provider router
        floating_ip = db.floating_ip_get_by_address(context,
                                                    floating_address)
        network_id = floating_ip['fixed_ip']['network_id']
        tenant_router_id = db.network_get(context, network_id)['uuid']

        LOG.debug("floating_ip: %s", floating_ip)
        LOG.debug("tenant_router_id: %s",  tenant_router_id)

        # take care of nova db record
        fixed_address = db.floating_ip_disassociate(context,
                                                    floating_address)

        conn = midonet.MidonetClient(FLAGS.mido_api_host, FLAGS.mido_api_port,
                                     FLAGS.mido_api_app,
                                     token=context.auth_token)

        # Get the link between this router ID to the provider router ID. 
        response, content = conn.get_peer_router_detail(tenant_router_id,
                                            FLAGS.mido_provider_router_id)
        provider_router_port_id = content['peerPortId'] 

        # Get routes to this port.
        response, content = conn.list_port_route(provider_router_port_id)
       
        # Go through the routes.
        for route in content:
            # Check if the destination IP is set to the floating IP.
            if route['dstNetworkAddr'] == floating_address:
                # Remove this route.
                response, _content = conn.delete_route(route['id'])
                LOG.info("route deleted: %s",  route['id'])

        # Get the NAT PREROUTING chain ID
        response, content = conn.get_chain_by_name(tenant_router_id, 'nat', 'pre_routing')
        chain_id = content['id']
        # Get all the routes for this chain.
        response, content = conn.list_rule(chain_id)
        for rule in content:
            # Check if this NAT rule is a DNAT rule and matches the floating ipPREROUTING
            if rule['type'] == 'dnat' and rule['nwDstAddress'] == floating_address:
                response, _content = conn.delete_rule(rule['id'])
                LOG.info("dnat rule deleted: %s",  rule['id'])

        # Get the NAT POSTROUTING chain ID
        response, content = conn.get_chain_by_name(tenant_router_id, 'nat', 'post_routing')
        chain_id = content['id']
        # Get all the routes for this chain.
        response, content = conn.list_rule(chain_id)
        for rule in content:
            # Check if this NAT rule is a SNAT rule and matches the floating ip
            if rule['type'] == 'snat' and (floating_address in rule['natTargets'][0][0]):
                response, _content = conn.delete_rule(rule['id'])
                LOG.info("snat rule deleted: %s",  rule['id'])

    def validate_networks(self, context, networks):
        if networks is None:
            return

        conn = midonet.MidonetClient(FLAGS.mido_api_host, FLAGS.mido_api_port,
                                     FLAGS.mido_api_app,
                                     token=context.auth_token)
        project_id = context.project_id
        for (net_id, _i) in networks:
            self.ipam.verify_subnet_exists(context, project_id, net_id)
            if not conn.router_exists(project_id, net_id):
                raise exception.NetworkNotFound(network_id=net_id)

