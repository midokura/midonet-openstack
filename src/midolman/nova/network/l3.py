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


LOG = logging.getLogger(__name__)
FLAGS = flags.FLAGS


class MidonetL3Driver(L3Driver):
    """The L3 driver for Midonet"""
    def __init__(self):
        LOG.debug('__init__() called.')
        self.mido_conn = midonet_connection.get_connection()
        pass

    def initialize(self, **kwargs):
        LOG.debug('initialize() called: kwargs=%r', kwargs)
        pass

    def is_initialized(self):
        return True

    def initialize_network(self, cidr):
        LOG.debug('initialize_network() called: cidr=%r', cidr)
        pass

    def initialize_gateway(self, network_ref):
        LOG.debug('initialize_gateway() called: network_ref=%r', network_ref)
        pass

    def remove_gateway(self, network_ref):
        LOG.debug('remove_gateway() called: network_ref=%r', network_ref)
        pass

    def add_floating_ip(self, floating_ip, fixed_ip, l3_interface_id):
        LOG.debug('add_floating_ip() called: floating_ip=%r, fixed_ip=%r, l3_interface_id=%r',
                     floating_ip, fixed_ip, l3_interface_id)
        print 'add_floating_ip() called: floating_ip=%r, fixed_ip=%r, l3_interface_id=%r' % \
                                                      (floating_ip, fixed_ip, l3_interface_id)

        admin_context = context.get_admin_context()
        fixed_ip_ref = db.fixed_ip_get_by_address(admin_context, fixed_ip)

        # Get legacy network id (not uuid)
        network_id = fixed_ip_ref['network_id']

        # Get network ref
        network_ref = db.network_get(admin_context, network_id)
        print network_ref

        tenant_id = network_ref['project_id'] or FLAGS.quantum_default_tenant_id

        print 'tenant_id ', tenant_id
        # Search tenant router
        tenant_router_name = FLAGS.midonet_tenant_router_name_format % tenant_id

        response, routers = self.mido_conn.routers().list(tenant_id)
        print routers
        tenant_router_id = None
        for r in routers:
            if r['name'] == tenant_router_name:
                LOG.debug("Tenant Router found")
                found = True
                tenant_router_id = r['id']
        assert found

        response, link_router = self.mido_conn.routers().link_router_get(
                                                            tenant_id, tenant_router_id,
                                                            FLAGS.midonet_provider_router_id)
        print 'link_router: ', link_router
        provider_router_port_id = link_router['peerPortId']

        # Add a route to the fixed ip in the provider
        response, content = self.mido_conn.routes().create(
                                        FLAGS.midonet_admin_tenant,
                                        FLAGS.midonet_provider_router_id,
                                        'Normal',               # Type
                                        '0.0.0.0', 0,           # src (any) 
                                        fixed_ip, 32,           # dest (fixed_ip)
                                        100,                    # weight
                                        provider_router_port_id,# next hop port
                                        None)                   # next hop gateway
        print 'Router created: ', response

        response, chains = self.mido_conn.chains().list(tenant_id, tenant_router_id)
        print 'Chains: ', chains
        for c in chains:
            if c['name'] == 'pre_routing':
                pre_routing_chain_id = c['id']
            if c['name'] == 'post_routing':
                post_routing_chain_id = c['id']

        print 'pre_routing_chain_id ', pre_routing_chain_id
        print 'post_routing_chain_id ', post_routing_chain_id

        # Add DNAT rule to the tenant router
        response, content = self.mido_conn.rules().create_dnat_rule(
                                        tenant_id, tenant_router_id,
                                        pre_routing_chain_id, 
                                        floating_ip, fixed_ip)
        print 'Create DNAT ', response

        # Add SNAT rule to the tenant router
        response, content = self.mido_conn.rules().create_snat_rule(
                                        tenant_id, tenant_router_id,
                                        post_routing_chain_id, 
                                        floating_ip, fixed_ip)
        print 'Create NAT ', response

    def remove_floating_ip(self, floating_ip, fixed_ip, l3_interface_id):
        LOG.debug('remove_floating_ip() called: floating_ip=%r, fixed_ip=%r, l3_interface_id=%r',
                     floating_ip, fixed_ip, l3_interface_id)
        print 'remove_floating_ip() called: floating_ip=%r, fixed_ip=%r, l3_interface_id=%r'% \
                                                           (floating_ip, fixed_ip, l3_interface_id)


        # Get routes in the provider router
        response, routes = self.mido_conn.routes().list(
                                        FLAGS.midonet_admin_tenant,
                                        FLAGS.midonet_provider_router_id)
        print 'Routes: ', routes

        # Look for the route to the fixed_ip in the provider router
        for r in routes:
            if r['dstNetworkAddr'] == fixed_ip and r['dstNetworkLength'] == 32:
                route_id = r['id']
            
        print 'Route ID: ', route_id

        # Delete the route in the provider router
        response, content = self.mido_conn.routes().delete(
                                        FLAGS.midonet_admin_tenant,
                                        FLAGS.midonet_provider_router_id,
                                        route_id)
        #
        # Now take care of NAT rules
        #

        admin_context = context.get_admin_context()
        fixed_ip_ref = db.fixed_ip_get_by_address(admin_context, fixed_ip)

        # Get legacy network id (not uuid)
        network_id = fixed_ip_ref['network_id']

        # Get network ref
        network_ref = db.network_get(admin_context, network_id)
        print network_ref

        tenant_id = network_ref['project_id'] or FLAGS.quantum_default_tenant_id

        print 'tenant_id ', tenant_id
        # Search tenant router
        tenant_router_name = FLAGS.midonet_tenant_router_name_format % tenant_id

        response, routers = self.mido_conn.routers().list(tenant_id)
        print routers
        tenant_router_id = None
        for r in routers:
            if r['name'] == tenant_router_name:
                LOG.debug("Tenant Router found")
                found = True
                tenant_router_id = r['id']
        assert found

        response, chains = self.mido_conn.chains().list(tenant_id, tenant_router_id)
        print 'Chains: ', chains
        for c in chains:
            if c['name'] == 'pre_routing':
                pre_routing_chain_id = c['id']
            if c['name'] == 'post_routing':
                post_routing_chain_id = c['id']

        print 'pre_routing_chain_id ', pre_routing_chain_id
        print 'post_routing_chain_id ', post_routing_chain_id

       
        # DNAT
        response, rules = self.mido_conn.rules().list(
                                        tenant_id, tenant_router_id,
                                        pre_routing_chain_id)
        print 'Rules in pre_routing ', rules
        found = False
        for r in rules:
            if r['nwDstAddress'] == floating_ip and r['nwDstLength'] == 32:
                found = True
                print 'DNAT rule Found ', r
                dnat_id = r['id']
        assert found

        response, content = self.mido_conn.rules().delete(
                                        tenant_id, tenant_router_id,
                                        pre_routing_chain_id, dnat_id)
        print 'Delete dnat ', response 

        # SNAT
        response, rules = self.mido_conn.rules().list(
                                        tenant_id, tenant_router_id,
                                        post_routing_chain_id)
        print 'Rules in post_routing ', rules

        found = False
        for r in rules:
            if r['nwSrcAddress'] == fixed_ip and r['nwSrcLength'] == 32:
                found = True
                print 'SNAT rule Found ', r
                snat_id = r['id']
        assert found
        response, content = self.mido_conn.rules().delete(
                                        tenant_id, tenant_router_id,
                                        post_routing_chain_id, snat_id)
        print 'Delete dnat ', response 

    def add_vpn(self, public_ip, port, private_ip):
        LOG.debug('add_vpn() called: public_ip=%r, port=%r, private_ip=%r', public_ip, port, private_ip)
        pass

    def remove_vpn(self, public_ip, port, private_ip):
        LOG.debug('remove_vpn() called: public_ip=%r, port=%r, private_ip=%r', public_ip, port, private_ip)
        pass

    def teardown(self):
        LOG.debug('teardown() called')
        pass
