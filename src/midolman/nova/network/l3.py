# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2012 Midokura Japan KK
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

from nova import context
from nova import db
from nova import flags
from nova import log as logging
from nova.network.l3 import L3Driver

from midolman.nova.network import midonet_connection

# Add 'nova' prefix for nova's logging setting
LOG = logging.getLogger('nova...' + __name__)
FLAGS = flags.FLAGS


class MidonetL3Driver(L3Driver):
    """The L3 driver for Midonet"""
    def __init__(self):
        LOG.debug('__init__() called.')
        self.mido_conn = midonet_connection.get_connection()
        pass

    def initialize(self, **kwargs):
        LOG.debug('kwargs=%r', kwargs)
        pass

    def is_initialized(self):
        return True

    def initialize_network(self, cidr):
        LOG.debug('cidr=%r', cidr)
        pass

    def initialize_gateway(self, network_ref):
        LOG.debug('network_ref=%r', network_ref)
        pass

    def remove_gateway(self, network_ref):
        LOG.debug('network_ref=%r', network_ref)
        pass

    def add_floating_ip(self, floating_ip, fixed_ip, l3_interface_id):
        LOG.debug('floating_ip=%r, fixed_ip=%r, l3_interface_id=%r',
                  floating_ip, fixed_ip, l3_interface_id)

        admin_context = context.get_admin_context()
        fixed_ip_ref = db.fixed_ip_get_by_address(admin_context, fixed_ip)

        # Get legacy network id (not uuid)
        network_id = fixed_ip_ref['network_id']

        # Get network ref
        network_ref = db.network_get(admin_context, network_id)
        LOG.debug('network_ref: %r',  network_ref)

        tenant_id = network_ref['project_id'] or \
                        FLAGS.quantum_default_tenant_id

        LOG.debug('tenant_id: %r', tenant_id)
        # Search tenant router
        tenant_router_name = FLAGS.midonet_tenant_router_name_format % tenant_id

        response, routers = self.mido_conn.routers().list(tenant_id)
        LOG.debug('routers: %r', routers)
        tenant_router_id = None
        for r in routers:
            if r['name'] == tenant_router_name:
                LOG.debug("Tenant Router found: %r", r)
                found = True
                tenant_router_id = r['id']
        assert found

        response, link_router = self.mido_conn.routers().link_router_get(
                                    tenant_id, tenant_router_id,
                                    FLAGS.midonet_provider_router_id)
        LOG.debug('link_router: %r', link_router)
        provider_router_port_id = link_router['peerPortId']

        # Add a route for the floating ip in the provider
        response, content = self.mido_conn.routes().create(
                                FLAGS.midonet_provider_tenant_id,
                                FLAGS.midonet_provider_router_id,
                                'Normal',               # Type
                                '0.0.0.0', 0,           # src (any)
                                floating_ip, 32,        # dest
                                100,                    # weight
                                provider_router_port_id,# next hop port
                                                        #TODO put peer's IP addr
                                None)                   # next hop gw
        LOG.debug('Route created: %r', response)

        response, chains = self.mido_conn.chains().list(tenant_id,
                               tenant_router_id)
        LOG.debug('chains: %r', chains)
        for c in chains:
            if c['name'] == 'pre_routing':
                pre_routing_chain_id = c['id']
            if c['name'] == 'post_routing':
                post_routing_chain_id = c['id']

        LOG.debug('pre_routing_chain_id %r', pre_routing_chain_id)
        LOG.debug('post_routing_chain_id %r', post_routing_chain_id)

        # Add DNAT rule to the tenant router
        response, content = self.mido_conn.rules().create_dnat_rule(
                                        tenant_id, tenant_router_id,
                                        pre_routing_chain_id,
                                        floating_ip, fixed_ip)
        LOG.debug('Create DNAT: %r ', response)

        # Add SNAT rule to the tenant router
        response, content = self.mido_conn.rules().create_snat_rule(
                                        tenant_id, tenant_router_id,
                                        post_routing_chain_id,
                                        floating_ip, fixed_ip)
        LOG.debug('Create NAT: %r', response)

    def remove_floating_ip(self, floating_ip, fixed_ip, l3_interface_id):
        LOG.debug('floating_ip=%r, fixed_ip=%r, l3_interface_id=%r',
                  floating_ip, fixed_ip, l3_interface_id)


        # Get routes in the provider router
        response, routes = self.mido_conn.routes().list(
                                        FLAGS.midonet_provider_tenant_id,
                                        FLAGS.midonet_provider_router_id)
        LOG.debug('Routes: %r', routes)

        # Look for the route for the floating_ip in the provider router
        route_id = None
        for r in routes:
            if r['dstNetworkAddr'] == floating_ip and \
                   r['dstNetworkLength'] == 32:
                route_id = r['id']

        LOG.debug('Route ID to delete: %r', route_id)

        # Delete the route in the provider router
        try:
            response, content = self.mido_conn.routes().delete(
                                        FLAGS.midonet_provider_tenant_id,
                                        FLAGS.midonet_provider_router_id,
                                        route_id)
        except Exception as e:
            LOG.info('Delete route got an exception %r', e)
            LOG.debug('Keep going.')
        #
        # Now take care of NAT rules
        #

        admin_context = context.get_admin_context()
        fixed_ip_ref = db.fixed_ip_get_by_address(admin_context, fixed_ip)

        # Get legacy network id (not uuid)
        network_id = fixed_ip_ref['network_id']

        # Get network ref
        network_ref = db.network_get(admin_context, network_id)
        LOG.debug('network_ref: %r', network_ref)

        tenant_id = network_ref['project_id'] or \
                        FLAGS.quantum_default_tenant_id

        LOG.debug('tenant_id: %r', tenant_id)
        # Search tenant router
        tenant_router_name = \
            FLAGS.midonet_tenant_router_name_format % tenant_id

        response, routers = self.mido_conn.routers().list(tenant_id)
        LOG.debug('routers: %r', routers)
        tenant_router_id = None
        for r in routers:
            if r['name'] == tenant_router_name:
                LOG.debug("Tenant Router found")
                found = True
                tenant_router_id = r['id']
        assert found

        response, chains = self.mido_conn.chains().list(tenant_id,
                               tenant_router_id)
        LOG.debug('Chains: %r', chains)
        for c in chains:
            if c['name'] == 'pre_routing':
                pre_routing_chain_id = c['id']
            if c['name'] == 'post_routing':
                post_routing_chain_id = c['id']

        LOG.debug('pre_routing_chain_id %r', pre_routing_chain_id)
        LOG.debug('post_routing_chain_id %r', post_routing_chain_id)

        # DNAT
        response, rules = self.mido_conn.rules().list(
                                        tenant_id, tenant_router_id,
                                        pre_routing_chain_id)
        LOG.debug('Rules in pre_routing %r', rules)
        found = False
        for r in rules:
            if r['nwDstAddress'] == floating_ip and r['nwDstLength'] == 32:
                found = True
                LOG.debug('DNAT rule to delete found: %r', r)
                dnat_id = r['id']
        LOG.debug('DNAT rules found? %r', found)

        try:
            response, content = self.mido_conn.rules().delete(
                                        tenant_id, tenant_router_id,
                                        pre_routing_chain_id, dnat_id)
            LOG.debug('Delete dnat: %r', response)
        except Exception as e:
            LOG.info('Delete DNAT rule got an exception %r', e)
            LOG.debug('Keep going.')

        # SNAT
        response, rules = self.mido_conn.rules().list(
                                        tenant_id, tenant_router_id,
                                        post_routing_chain_id)
        LOG.debug('Rules in post_routing: %r', rules)

        found = False
        for r in rules:
            if r['nwSrcAddress'] == fixed_ip and r['nwSrcLength'] == 32:
                found = True
                LOG.debug('SNAT rule to delete found: %r', r)
                snat_id = r['id']
        assert found

        try:
            response, content = self.mido_conn.rules().delete(
                                        tenant_id, tenant_router_id,
                                        post_routing_chain_id, snat_id)
            LOG.debug('Delete dnat: %r', response)
        except Exception as e:
            LOG.info('Delete DNAT rule got an exception %r', e)
            LOG.debug('Keep going.')

    def add_vpn(self, public_ip, port, private_ip):
        LOG.debug('public_ip=%r, port=%r, private_ip=%r',
                  public_ip, port, private_ip)
        pass

    def remove_vpn(self, public_ip, port, private_ip):
        LOG.debug('public_ip=%r, port=%r, private_ip=%r',
                  public_ip, port, private_ip)
        pass

    def teardown(self):
        LOG.debug('teardown() called')
        pass
