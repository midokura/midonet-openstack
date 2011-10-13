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
from nova import log as logging
from nova.network.manager import FlatManager 
from nova.network.manager import RPCAllocateFixedIP 
from nova.network.manager import FloatingIP 
from nova.db import api
from nova import flags
from nova import exception

from midolman.nova import flags as mido_flags

FLAGS = flags.FLAGS
LOG = logging.getLogger('midolman.nova.network.manager')


def _extract_id_from_header_location(response):
    return response['location'].split('/')[-1]

class MidonetManager(FloatingIP, FlatManager):

    def create_network(self, context, label, cidr, multi_host,
                       network_size, cidr_v6, gateway_v6, bridge,
                       bridge_interface, dns1=None, dns2=None, **kwargs):
        LOG.info("---- Midonet Manager. create_networks: %r", kwargs)

        # Create a network in Nova
        networks = super(MidonetManager, self).create_networks(context, label,
                         cidr, multi_host, 1,
                        network_size, cidr_v6, gateway_v6, bridge,
                        bridge_interface, dns1, dns2, **kwargs)
        if networks is None or len(networks) == 0:
            return None
        network = networks[0]
        LOG.debug("  created network: %s", network)

        mc = midonet.MidonetClient(context.auth_token, FLAGS.mido_api_host,
                                   FLAGS.mido_api_port, FLAGS.mido_api_app)
        tenant_id = kwargs.get('project_id')
        router_name = label

        LOG.debug('  tenant_id: %s', tenant_id)
        LOG.debug('  router_name %s', router_name)

        # Create the tenant.  Swallow any error here.(YUCK!)
        _response, _content = mc.create_tenant(tenant_id)

        # Create a router for this tenant.
        response, _content = mc.create_router(tenant_id, router_name)
        tenant_router_id = _extract_id_from_header_location(response)
        LOG.debug('  tenant_router_id: %s', tenant_router_id)

        # Link this router to the provider router via logical ports.
        response, content = mc.link_router(tenant_router_id,
                                          FLAGS.mido_link_port_network_address,
                                          FLAGS.mido_link_port_network_len,
                                          FLAGS.mido_link_local_port_network_address,
                                          FLAGS.mido_link_peer_port_network_address,
                                          FLAGS.mido_provider_router_id)

        provider_port = content['peerPortId']
        tenant_port = content['portId']

        # Add the default route in the tenant router.
        response, content = mc.create_route(tenant_router_id, '0.0.0.0', 0, 
                                            'Normal',
                                            '0.0.0.0', 0, tenant_port,
                                            None, 100);

        # Hack to put uuid and tenant_id (into project_id) inside database
        api.network_update(context, network.id, {"project_id": tenant_id, 
            "uuid": tenant_router_id})
        return network

    def delete_network(self, context, fixed_range, require_disassociated=True):
        LOG.debug("---- delete_network: %r", fixed_range)
        # Get the router ID
        network = self.db.network_get_by_cidr(context, fixed_range)
        router_id = network['uuid']

        # Delete from the DB.
        super(MidonetManager, self).delete_network(context, fixed_range) 

        # Delete the router.
        mc = midonet.MidonetClient(context.auth_token, FLAGS.mido_api_host,
                                   FLAGS.mido_api_port, FLAGS.mido_api_app)
        response, content = mc.delete_router(router_id)

    def get_instance_nw_info(self, context, instance_id,
                             instance_type_id, host):
        # Need to set UUID
        nw_info = super(MidonetManager, self).get_instance_nw_info(context,
            instance_id, instance_type_id, host)
        for nw in nw_info:
            nw_dict = nw[0]
            net = api.network_get(context, nw_dict['id'])
            nw_dict['uuid'] = net['uuid'] 
        return nw_info

    def _setup_network(self, context, network_ref):
        pass

    def associate_floating_ip(self, context, floating_address, fixed_address):
        """Associates a floating ip to a fixed ip."""
        floating_ip = self.db.floating_ip_get_by_address(context,
                                                         floating_address)
        if floating_ip['fixed_ip']:
            raise exception.FloatingIpAlreadyInUse(
                            address=floating_ip['address'],
                            fixed_ip=floating_ip['fixed_ip']['address'])

        self.db.floating_ip_fixed_ip_associate(context,
                                               floating_address,
                                               fixed_address,
                                               self.host)

        mc = midonet.MidonetClient(context.auth_token, FLAGS.mido_api_host,
                                   FLAGS.mido_api_port, FLAGS.mido_api_app)

        # Determine the network that the fixed IP belongs to.
        floating_ip = self.db.floating_ip_get_by_address(context,
                                                         floating_address)
        network_id = floating_ip['fixed_ip']['network_id']
        tenant_router_id = self.db.network_get(context, network_id)['uuid']

        LOG.debug("  floating_ip: %s", floating_ip)
        LOG.debug("  tenant_router_id: %s", tenant_router_id)

        # Get the logical router port UUID that connects the provider router
        # this tenant router.
        response, content = mc.get_peer_router_detail(tenant_router_id,
                                               FLAGS.mido_provider_router_id)
        provider_router_port_id = content['peerPortId']  
        LOG.debug("  provider_router_port_id: %s", provider_router_port_id)

        # Add a DNAT rule 
        response, content = mc.create_dnat_rule(
             tenant_router_id, floating_address,
             floating_ip['fixed_ip']['address'])

        # Add a SNAT rule 
        response, content = mc.create_snat_rule(
             tenant_router_id, floating_address,
             floating_ip['fixed_ip']['address'])
                                                
        # Set up a route in the provider router.
        response, content = mc.create_route(FLAGS.mido_provider_router_id,
                                            '0.0.0.0', 0, 'Normal',
                                            floating_address, 32, 
                                            provider_router_port_id, None, 100)

    def disassociate_floating_ip(self, context, floating_address):
        """Disassociates a floating ip."""

        # Get the logical router port UUID that connects the provider router
        floating_ip = self.db.floating_ip_get_by_address(context,
                                                         floating_address)
        network_id = floating_ip['fixed_ip']['network_id']
        tenant_router_id = self.db.network_get(context, network_id)['uuid']

        LOG.debug("floating_ip: %s", floating_ip)
        LOG.debug("tenant_router_id: %s",  tenant_router_id)

        # take care of nova db record
        fixed_address = self.db.floating_ip_disassociate(context,
                                                         floating_address)

        mc = midonet.MidonetClient(context.auth_token, FLAGS.mido_api_host,
                                   FLAGS.mido_api_port, FLAGS.mido_api_app)

        # Get the link between this router ID to the provider router ID. 
        response, content = mc.get_peer_router_detail(tenant_router_id,
                                            FLAGS.mido_provider_router_id)
        provider_router_port_id = content['peerPortId'] 

        # Get routes to this port.
        response, content = mc.list_port_route(provider_router_port_id)
       
        # Go through the routes.
        for route in content:
            # Check if the destination IP is set to the floating IP.
            if route['dstNetworkAddr'] == floating_address:
                # Remove this route.
                response, _content = mc.delete_route(route['id'])
                LOG.info("route deleted: %s",  route['id'])

        # Get the NAT PREROUTING chain ID
        response, content = mc.get_chain_by_name(tenant_router_id, 'nat', 'pre_routing')
        chain_id = content['id']
        # Get all the routes for this chain.
        response, content = mc.list_rule(chain_id)
        for rule in content:
            # Check if this NAT rule is a DNAT rule and matches the floating ipPREROUTING
            if rule['type'] == 'dnat' and rule['nwDstAddress'] == floating_address:
                response, _content = mc.delete_rule(rule['id'])
                LOG.info("dnat rule deleted: %s",  rule['id'])

        # Get the NAT POSTROUTING chain ID
        response, content = mc.get_chain_by_name(tenant_router_id, 'nat', 'post_routing')
        chain_id = content['id']
        # Get all the routes for this chain.
        response, content = mc.list_rule(chain_id)
        for rule in content:
            # Check if this NAT rule is a SNAT rule and matches the floating ip
            if rule['type'] == 'snat' and (floating_address in rule['natTargets'][0][0]):
                response, _content = mc.delete_rule(rule['id'])
                LOG.info("snat rule deleted: %s",  rule['id'])

    def validate_networks(self, context, networks):
        LOG.debug("---Midonet validate_networks [networks] ---%r", networks)

        if networks is None:
            return

        mc = midonet.MidonetClient(context.auth_token, FLAGS.mido_api_host,
                                   FLAGS.mido_api_port, FLAGS.mido_api_app)

        for (net_id, _i) in networks:
            # make sure that there's a entry in the networks table
            network = self.db.network_get_by_uuid(context, net_id)

            tenant_id = network['project_id']
            response, content = mc.list_router(tenant_id)

            if response['status'] == '200':
                routers = content
                for r in routers:
                    LOG.debug("  validate_networks-------: %r", r)
                    if r['id'] == net_id:
                        LOG.debug("    validate_networks-------: FOUND")
                        found = True
                if not found:
                    raise exception.NetworkNotFound(network_id=net_id)
            else:

                raise exception.NetworkNotFound(network_id=net_id)
				

    # quick and dirty hack. will clean up by overriding allocate_for_instance
    def _get_networks_for_instance(self, context, instance_id, project_id,
                                   requested_networks=None):
        """Determine which networks an instance should connect to."""
        # get networks associated with project
        if requested_networks is not None and len(requested_networks) != 0:
            network_uuids = [uuid for (uuid, fixed_ip) in requested_networks]
            networks = []
            for uuid in network_uuids:
                networks.append(self.db.network_get_by_uuid(context, uuid))
                                                    
        else:
            networks = self.db.project_get_networks(context, project_id)
        LOG.debug("  networks-------: %r", networks)
        return networks


