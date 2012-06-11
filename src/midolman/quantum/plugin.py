# vim: tabstop=4 shiftwidth=4 softtabstop=4
# Copyright 2011 Midokura Japan, KK
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
# @author: Tomoe Sugihara, Midokura Japan, KK

import ConfigParser
import logging
import sys
import webob.exc as exc

from quantum.quantum_plugin_base import QuantumPluginBase
from quantum.api.api_common import OperationalStatus
from quantum.common.config import find_config_file
from quantum.common import exceptions as exception

from midonet.client import MidonetClient
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

        self.mido_conn = MidonetClient(
                            midonet_uri=midonet_uri,
                            ks_uri=keystone_uri,
                            username=admin_user, password=admin_password,
                            tenant_id=self.provider_tenant_id)
        self.chain_manager = ChainManager(self.mido_conn)
        self.pg_manager = PortGroupManager(self.mido_conn)

        # See if the provider tenant and router exist. If not, create them.
        try:
            self.mido_conn.tenants().get(self.provider_tenant_id)
        except exc.HTTPNotFound:
            LOG.debug('Admin tenant(%r) not found. Creating...' %
                                                            self.provider_tenant_id)
            self.mido_conn.tenants().create(self.provider_tenant_id)
        try:
            self.mido_conn.routers().get(self.provider_tenant_id,
                                         self.provider_router_id)
        except LookupError as e:
            LOG.debug('Provider router(%r) not found. Creating...' %
                                                        self.provider_router_id)
            self.mido_conn.routers().create(self.provider_tenant_id,
                                            self.provider_router_name,
                                            router_id=self.provider_router_id)

    def get_all_networks(self, tenant_id, filter_opts=None):
        """
        Returns a dictionary containing all
        <network_uuid, network_name> for
        the specified tenant.
        """
        LOG.debug("get_all_networks() called with tenant_id %r", tenant_id)

        bridges = []
        try:
            response, bridges = self.mido_conn.bridges().list(tenant_id)
            LOG.debug("Bridges: %r", bridges)
        except exc.HTTPNotFound as e:
            LOG.debug(e)
            LOG.debug("Returning empty list for non-existent tenant")

        res = []
        for b in bridges:
            res.append({'net-id': b['id'], 'net-name': b['name'],
                        'net-op-status': OperationalStatus})
        return res

    def create_network(self, tenant_id, net_name, **kwargs):
        """
        Creates a new Virtual Network, and assigns it
        a symbolic name.
        """
        LOG.debug("tenant_id=%r, net_name=%r, kwargs: %r",
                  tenant_id, net_name, kwargs)

        try:
            self.mido_conn.tenants().get(tenant_id)

        except exc.HTTPNotFound:
            LOG.debug("Creating tenant: %r", tenant_id)
            self.mido_conn.tenants().create(tenant_id)
        except Exception as e:
            LOG.debug("Create tenant in midonet got exception: %r", e)
            raise e

        tenant_router_name = self.tenant_router_name
        LOG.debug("Midonet Tenant Router Name: %r", tenant_router_name)
        # do get routers to see if the tenant already has its tenant router.
        response, content = self.mido_conn.routers().list(tenant_id)

        found = False
        tenant_router_id = None
        for r in content:
            if r['name'] == tenant_router_name:
                LOG.debug("Tenant Router found")
                found = True
                tenant_router_id = r['id']

        # if not found, create the tenant router and link it to the provider's
        if not found:

            # create in-n-out chains for the tenant router
            response, content = self.mido_conn.chains().create(tenant_id,
                    ChainManager.TENANT_ROUTER_IN)
            response, in_chain = self.mido_conn.get(response['location'])

            response, content = self.mido_conn.chains().create(tenant_id,
                    ChainManager.TENANT_ROUTER_OUT)
            response, out_chain = self.mido_conn.get(response['location'])

            response, content = self.mido_conn.routers().create(
                                                 tenant_id, tenant_router_name,
                                                 in_chain['id'],
                                                 out_chain['id'])
            response, tenant_router = self.mido_conn.get(response['location'])
            tenant_router_id = tenant_router['id']

            # Create a port in the provider router
            response, content = self.mido_conn.router_ports().create(
                    self.provider_tenant_id,
                    self.provider_router_id,
                    PortType.LOGICAL_ROUTER,
                    '10.0.0.0', 30,
                    '10.0.0.1')
            response, provider_port = self.mido_conn.get(response['location'])
            LOG.debug('provider_port=%r', provider_port)

            # Create a port in the tenant router
            response, content = self.mido_conn.router_ports().create(
                    tenant_id,
                    tenant_router_id,
                    PortType.LOGICAL_ROUTER,
                    '10.0.0.0', 30,
                    '10.0.0.2')
            response, tenant_port = self.mido_conn.get(response['location'])
            LOG.debug('tenant_port=%r', tenant_port)

            # Link them
            response, content = self.mido_conn.router_ports().link(
                    self.provider_tenant_id,
                    self.provider_router_id,
                    provider_port['id'],
                    tenant_port['id'])

            # Set default route to uplink
            tenant_uplink_port_id = tenant_port['id']
            response, content = self.mido_conn.routes().create(
                    tenant_id,
                    tenant_router_id,
                    'Normal',             # type
                    '0.0.0.0', 0,         # source
                    '0.0.0.0', 0,         # destination
                    100,                  # weight
                    tenant_uplink_port_id,# next hop port
                    None)                 # next hop gateway

            # NOTE:create chain and port_groups for default security groups
            # These should be supposedly handled by security group handler,
            # but handler doesn't get called for deafault security group
            self.chain_manager.create_for_sg(tenant_id, None, 'default')
            self.pg_manager.create(tenant_id, None, 'default')

        # create a bridge for this network
        response, content = self.mido_conn.bridges().create(tenant_id, net_name)
        response, content = self.mido_conn.get(
                                    response['location'])
        bridge_id = content['id']
        net_name = content['name']

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
        response, content = self.mido_conn.routers().list(tenant_id)

        tenant_router_id = None
        for r in content:
            if r['name'] == tenant_router_name:
                LOG.debug("Tenant Router found")
                tenant_router_id = r['id']

        # Delete link between the tenant router and the bridge
        # look for the port that is connected to the bridge
        response, tr_ports = self.mido_conn.router_ports().list(
                tenant_id, tenant_router_id)

        LOG.debug('tr_ports=%r', tr_ports)
        found = False
        for p in tr_ports:
            if p['type'] == PortType.MATERIALIZED_ROUTER:
                continue
            response, peer_port = self.mido_conn.get(p['peer'])
            if peer_port['deviceId'] == net_id:
                response, content = self.mido_conn.router_ports().unlink(
                        tenant_id, tenant_router_id, p['id'])
                found = True
        assert found

        # Delete the bridge
        try:
            response, content = self.mido_conn.bridges().delete(
                    tenant_id, net_id)
        except Exception as e:
            LOG.debug("Delete bridge got an exception: %r.", e)
            LOG.debug("Since unlink succeeded, the exception was swallowed")

    def get_network_details(self, tenant_id, net_id):
        """
        Get network information
        """
        LOG.debug("get_network_details() called: tenant_id=%r, net_id=%r",
                  tenant_id, net_id)

        res = {}
        try:
            response, bridge = self.mido_conn.bridges().get(tenant_id, net_id)
            LOG.debug("Bridge: %r", bridge)
            res = {'net-id': bridge['id'], 'net-name': bridge['name'],
                   'net-op-status': 'UP'}
        except LookupError as e:
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
        response, ports = self.mido_conn.bridge_ports().list(tenant_id, net_id)
        return [{'port-id': str(p['id'])} for p in ports]

    def create_port(self, tenant_id, net_id, port_state=None, **kwargs):

        """
        Creates a port on the specified Virtual Network.
        """
        LOG.debug("create_port() called: tenant_id=%r, net_id=%r",
                  tenant_id, net_id)
        LOG.debug("     port_state=%r, kwargs:%r", port_state, kwargs)

        response, bridge = self.mido_conn.bridges().get(tenant_id, net_id)
        bridge_uuid = bridge['id']
        response, content = self.mido_conn.bridge_ports().create(
                tenant_id, bridge_uuid, PortType.MATERIALIZED_BRIDGE)
        response, bridge_port = self.mido_conn.get(response['location'])
        LOG.debug('Bridge port=%r is created on bridge=%r',
                                                bridge_port['id'], bridge_uuid)

        port = {'port-id': bridge_port['id'],
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
        response, content = self.mido_conn.bridge_ports().delete(
                                                    tenant_id, net_id, port_id)
        LOG.debug('delete_port: response=%r, content=%r', response, content)

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

        response, bridge_port = self.mido_conn.bridge_ports().get(
                                                    tenant_id, net_id, port_id)
        LOG.debug("Got Bridge port=%r", bridge_port)

        if bridge_port['type'] == PortType.MATERIALIZED_BRIDGE:
            attachment = bridge_port['vifId']
        else:
            attachment = None

        port = {'port-id': bridge_port['id'],
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
        response, bridge_port = self.mido_conn.bridge_ports().get(tenant_id,
                net_id, port_id)
        bridge_port['vifId'] = vif_id
        response, bridge_port = self.mido_conn.bridge_ports().update(tenant_id,
                net_id, port_id, bridge_port)

        LOG.debug("bridge_port=%r is updated.", bridge_port)

    def unplug_interface(self, tenant_id, net_id, port_id):
        """
        Detaches a remote interface from the specified port on the
        specified Virtual Network.
        """
        LOG.debug("tenant_id=%r, net_id=%r, port_id=%r",tenant_id, net_id,
                port_id)
        response, bridge_port = self.mido_conn.bridge_ports().get(
                                                     tenant_id, net_id, port_id)
        LOG.debug('bridge_port: %r', bridge_port)
        response, bridge_port = self.mido_conn.bridge_ports().get(tenant_id,
                net_id, port_id)
        bridge_port['vifId'] = None
        response, bridge_port = self.mido_conn.bridge_ports().update(tenant_id,
                net_id, port_id, bridge_port)


    supported_extension_aliases = ["FOXNSOX"]

    def method_to_support_foxnsox_extension(self):
        LOG.debug("method_to_support_foxnsox_extension() called\n")


