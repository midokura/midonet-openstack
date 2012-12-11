# vim: tabstop=4 shiftwidth=4 softtabstop=4
# Copyright (C) 2012 Midokura Japan K.K.
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

import ConfigParser
import logging
import sys
import webob.exc as exc

from quantum.quantum_plugin_base import QuantumPluginBase
from quantum.api.api_common import OperationalStatus
from quantum.common.config import find_config_file
from quantum.common import exceptions as exception

from midonet.auth.keystone import KeystoneAuth
from midonet.client.mgmt import MidonetMgmt
from midonet.client.web_resource import WebResource
from midonet.api import PortType
from midolman.common.openstack import RouterName, ChainManager, PortGroupManager


LOG = logging.getLogger('MidonetPlugin')


class MidonetPlugin(QuantumPluginBase):

    def __init__(self):
        config = ConfigParser.ConfigParser()

        config_file = find_config_file({"plugin":"midonet"}, None,
                                        "midonet_plugin.ini")
        if not config_file:
            raise Exception("Configuration file \"%s\" doesn't exist" %
                             "midonet_plugin.ini")

        # Read config values
        config.read(config_file)
        midonet_uri = config.get('midonet', 'midonet_uri')
        self.provider_router_id = config.get('midonet', 'provider_router_id')

        if config.has_option('midonet', 'provider_router_name'):
            self.provider_router_name = config.get('midonet',
                                                    'provider_router_name')
        else:
            self.provider_router_name = RouterName.PROVIDER_ROUTER

        if config.has_option('midonet', 'tenant_router_name'):
            self.tenant_router_name = config.get('midonet',
                                                    'tenant_router_name')
        else:
            self.tenant_router_name = RouterName.TENANT_ROUTER

        keystone_uri = config.get('keystone',
                                              'keystone_uri')
        admin_user = config.get('keystone', 'admin_user')
        admin_password = config.get('keystone', 'admin_password')
        self.provider_tenant_id = config.get('keystone', 'provider_tenant_id')

        LOG.debug('------midonet plugin config:')
        LOG.debug('midonet_uri: %r', midonet_uri)
        LOG.debug('provider_router_id: %r', self.provider_router_id)
        LOG.debug('keystone_uri: %r', keystone_uri)
        LOG.debug('admin_user: %r', admin_user)
        LOG.debug('admin_password: %r', admin_password)
        LOG.debug('provider_tenant_id: %r',  self.provider_tenant_id)

        auth = KeystoneAuth(keystone_uri, admin_user, admin_password,
                            tenant_id=self.provider_tenant_id)
        web_resource = WebResource(auth)
        self.mido_conn = MidonetMgmt(midonet_uri, web_resource, LOG)
        self.chain_manager = ChainManager(self.mido_conn)
        self.pg_manager = PortGroupManager(self.mido_conn)

        try:
            self.mido_conn.get_router(self.provider_router_id)
        except exc.HTTPNotFound, e:
            LOG.debug('Provider router(%r) not found. Creating...' %
                                                        self.provider_router_id)
            router = self.mido_conn.add_router().tenant_id(
                self.provider_tenant_id).name(
                self.provider_router_name)
            router.dto['id'] = self.provider_router_id
            router.create()

    def get_all_networks(self, tenant_id, filter_opts=None):
        """
        Returns a dictionary containing all
        <network_uuid, network_name> for
        the specified tenant.
        """
        LOG.debug("get_all_networks() called with tenant_id %r", tenant_id)

        bridges = []
        try:
            bridges = self.mido_conn.get_bridges({'tenant_id': tenant_id})
            LOG.debug("Bridges: %r", bridges)
        except exc.HTTPNotFound as e:
            LOG.debug(e)
            LOG.debug("Returning empty list for non-existent tenant")

        res = []
        for b in bridges:
            res.append({'net-id': b.get_id(), 'net-name': b.get_name(),
                        'net-op-status': OperationalStatus})
        return res

    def create_network(self, tenant_id, net_name, **kwargs):
        """
        Creates a new Virtual Network, and assigns it
        a symbolic name.
        """
        LOG.debug("tenant_id=%r, net_name=%r, kwargs: %r",
                  tenant_id, net_name, kwargs)

        tenant_router_name = self.tenant_router_name
        LOG.debug("Midonet Tenant Router Name: %r", tenant_router_name)
        # do get routers to see if the tenant already has its tenant router.
        content = self.mido_conn.get_routers({'tenant_id': tenant_id})

        found = False
        tenant_router_id = None
        for r in content:
            if r.get_name() == tenant_router_name:
                LOG.debug("Tenant Router found")
                found = True
                tenant_router_id = r.get_id()
                break

        # if not found, create the tenant router and link it to the provider's
        if not found:

            # create in-n-out chains for the tenant router
            in_chain = self.mido_conn.add_chain().tenant_id(tenant_id).name(
                ChainManager.TENANT_ROUTER_IN).create()

            out_chain = self.mido_conn.add_chain().tenant_id(tenant_id).name(
                ChainManager.TENANT_ROUTER_OUT).create()

            tenant_router = self.mido_conn.add_router().tenant_id(
                tenant_id).name(tenant_router_name).inbound_filter_id(
                in_chain.get_id()).outbound_filter_id(
                    out_chain.get_id()).create()
            tenant_router_id = tenant_router.get_id()

            # Create a port in the provider router
            provider_router = self.mido_conn.get_router(
                self.provider_router_id,)
            provider_port = provider_router.add_interior_port().network_address(
                '169.254.255.0').network_length(30).port_address(
                '169.254.255.1').create()
            LOG.debug('provider_port=%r', provider_port)

            # Create a port in the tenant router
            tenant_port = tenant_router.add_interior_port().network_address(
                '169.254.255.0').network_length(30).port_address(
                '169.254.255.2').create()
            LOG.debug('tenant_port=%r', tenant_port)

            # Link them
            tenant_port.link(provider_port.get_id())

            # Set default route to uplink
            tenant_uplink_port_id = tenant_port.get_id()
            tenant_router.add_route().type('Normal').src_network_addr(
                '0.0.0.0').src_network_length(0).dst_network_addr(
                '0.0.0.0').dst_network_length(0).weight(100).next_hop_port(
                    tenant_uplink_port_id).create()

            # NOTE:create chain and port_groups for default security groups
            # These should be supposedly handled by security group handler,
            # but handler doesn't get called for deafault security group
            self.chain_manager.create_for_sg(tenant_id, None, 'default')
            self.pg_manager.create(tenant_id, None, 'default')

        # create a bridge for this network
        content = self.mido_conn.add_bridge().tenant_id(
            tenant_id).name(net_name).create()
        bridge_id = content.get_id()
        net_name = content.get_name()

        network = {'net-id': bridge_id,
                'net-name': net_name,
                'net-op-status': OperationalStatus}
        return network

    def delete_network(self, tenant_id, net_id):
        """
        Deletes the network with the specified network identifier
        belonging to the specified tenant.
        """
        LOG.debug("delete_network() called. tenant_id=%r, net_id=%r",
                                                            tenant_id, net_id)

        tenant_router_name = self.tenant_router_name
        LOG.debug("Midonet Tenant Router Name: %r", tenant_router_name)
        # do get routers to see if the tenant already has its tenant router.
        content = self.mido_conn.get_routers({'tenant_id': tenant_id})

        tenant_router_id = None
        tenant_router = None
        for r in content:
            if r.get_name() == tenant_router_name:
                LOG.debug("Tenant Router found")
                tenant_router_id = r.get_id()
                tenant_router = r
                break

        # Delete link between the tenant router and the bridge
        tr_pps = tenant_router.get_peer_ports()

        LOG.debug('Tenant router peer ports=%r', tr_pps)
        found = False
        for p in tr_pps:
            if p.get_type() == PortType.EXTERIOR_ROUTER:
                continue
            if p.get_device_id() == net_id:
                tr_port = p.get_peer_id()
                br_port = p.get_id()
                found = True
                p.unlink()
                break
        assert found

        # Delete the bridge
        try:
            bridge = self.mido_conn.get_bridge(net_id)
            bridge.delete()
                    
        except Exception as e:
            LOG.debug('Delete bridge got an exception: %r.', e)
            raise exception.Error('Failed to delete the bridge=%s. ' % net_id +
                                  'Link between %r and %r must be put back.' %
                                  (tr_port, br_port))

        # Delete the interior port in tenant router
        self.mido_conn.get_port(tr_port).delete()

        # Delete routes destined to the tenant router port
        routes = tenant_router.get_routes()
        for r in routes:
            if r.get_next_hop_port() == tr_port:
                LOG.debug('delete route=%r', r.get_id())
                r.delete()

    def get_network_details(self, tenant_id, net_id):
        """
        Get network information
        """
        LOG.debug("get_network_details() called: tenant_id=%r, net_id=%r",
                  tenant_id, net_id)

        res = {}
        try:
            bridge = self.mido_conn.get_bridge(net_id)
            LOG.debug("Bridge: %r", bridge)
            res = {'net-id': bridge.get_id(), 'net-name': bridge.get_name(),
                   'net-op-status': 'UP'}
        except exc.HTTPNotFound as e:
            LOG.debug("Bridge %r not found", net_id)
            raise exception.NetworkNotFound(net_id=net_id)

        return res

    def update_network(self, tenant_id, net_id, **kwargs):
        LOG.debug("update_network() called")

    def get_all_ports(self, tenant_id, net_id, **kwargs):
        """
        Retrieves all port identifiers belonging to the
        specified Virtual Network.
        """
        LOG.debug("get_all_ports() called: tenant_id=%r, net_id=%r, kwargs=%r",
                                                      tenant_id, net_id, kwargs)
        bridge = self.mido_conn.get_bridge(net_id)
        ports = bridge.get_ports()
        return [{'port-id': str(p.get_id())} for p in ports]

    def create_port(self, tenant_id, net_id, port_state=None, **kwargs):

        """
        Creates a port on the specified Virtual Network.
        """
        LOG.debug("create_port() called: tenant_id=%r, net_id=%r",
                  tenant_id, net_id)
        LOG.debug("     port_state=%r, kwargs:%r", port_state, kwargs)

        bridge = self.mido_conn.get_bridge(net_id)
        bridge_uuid = bridge.get_id()
        bridge_port = bridge.add_exterior_port().create()
        LOG.debug('Bridge port=%r is created on bridge=%r',
                                                bridge_port.get_id(), bridge_uuid)

        port = {'port-id': bridge_port.get_id(),
                'port-state': 'ACTIVE',
                'port-op-status': 'UP',
                'net-id': net_id}
        return port

    def delete_port(self, tenant_id, net_id, port_id):
        """
        Deletes a port on a specified Virtual Network,
        if the port contains a remote interface attachment,
        the remote interface is first un-plugged and then the port
        is deleted.
        """
        LOG.debug("delete_port() called. tenant_id=%r, net_id=%r, port_id=%r",
                                                    tenant_id, net_id, port_id)
        bridge = self.mido_conn.get_bridge(net_id)
        self.mido_conn.get_port(port_id).delete()
        LOG.debug('delete_port:')

    def update_port(self, tenant_id, net_id, port_id, **kwargs):
        """
        Updates the attributes of a port on the specified Virtual Network.
        """
        LOG.debug("update_port() called\n")

    def get_port_details(self, tenant_id, net_id, port_id):
        """
        This method allows the user to retrieve a remote interface
        that is attached to this particular port.
        """
        LOG.debug("get_port_details() called: tenant_id=%r, net_id=%r",
                  tenant_id, net_id)
        LOG.debug("    port_id=%r", port_id)

        bridge = self.mido_conn.get_bridge(net_id)
        bridge_port = self.mido_conn.get_port(port_id)
        LOG.debug("Got Bridge port=%r", bridge_port)

        if bridge_port.get_type() == PortType.EXTERIOR_BRIDGE:
            attachment = bridge_port.get_vif_id()
        else:
            attachment = None

        port = {'port-id': bridge_port.get_id(),
                'port-state': 'ACTIVE',
                'port-op-status': 'UP',
                'net-id': net_id,
                'attachment': attachment}
        return port

    def plug_interface(self, tenant_id, net_id, port_id, vif_id):
        """
        Attaches a remote interface to the specified port on the
        specified Virtual Network.
        """
        LOG.debug("tenant_id=%r, net_id=%r, port_id=%r, vif_id=%r",
                tenant_id, net_id, port_id, vif_id)
        bridge = self.mido_conn.get_bridge(net_id)
        bridge_port = self.mido_conn.get_port(port_id)
        bridge_port.vif_id(vif_id).update()

        LOG.debug("bridge_port=%r is updated.", bridge_port)

    def unplug_interface(self, tenant_id, net_id, port_id):
        """
        Detaches a remote interface from the specified port on the
        specified Virtual Network.
        """
        LOG.debug("tenant_id=%r, net_id=%r, port_id=%r",tenant_id, net_id,
                port_id)
        bridge = self.mido_conn.get_bridge(net_id)
        bridge_port = self.mido_conn.get_port(port_id)
        LOG.debug('bridge_port: %r', bridge_port)
        bridge_port.vif_id(None).update()


    supported_extension_aliases = ["FOXNSOX"]

    def method_to_support_foxnsox_extension(self):
        LOG.debug("method_to_support_foxnsox_extension() called\n")


