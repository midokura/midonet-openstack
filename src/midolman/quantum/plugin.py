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

from midonet.client import MidonetClient


LOG = logging.getLogger('MidonetPlugin')


class MidonetPlugin(QuantumPluginBase):

    def __init__(self):
        config = ConfigParser.ConfigParser()

        config_file = find_config_file({"plugin":"midonet"}, None, "midonet_plugin.ini")
        if not config_file:
            raise Exception("Configuration file \"%s\" doesn't exist" % "midonet_plugin.ini")

        # Read config values
        config.read(config_file)
        midonet_uri = config.get('midonet', 'midonet_uri')
        self.provider_router_id = config.get('midonet', 'provider_router_id')
        self.provider_router_name = config.get('midonet', 'provider_router_name')
        self.tenant_router_name_format = config.get('midonet', 'tenant_router_name_format')

        keystone_tokens_endpoint = config.get('keystone', 'keystone_tokens_endpoint')
        admin_user = config.get('keystone', 'admin_user')
        admin_password = config.get('keystone', 'admin_password')
        self.admin_tenant = config.get('keystone', 'admin_tenant')

        LOG.debug('------midonet plugin config:')
        LOG.debug('midonet_uri: %r', midonet_uri)
        LOG.debug('provider_router_id: %r', self.provider_router_id)
        LOG.debug('keystone_tokens_endpoint: %r', keystone_tokens_endpoint)
        LOG.debug('admin_user: %r', admin_user)
        LOG.debug('admin_password: %r', admin_password)
        LOG.debug('admin_tenant: %r',  self.admin_tenant)

        self.mido_conn = MidonetClient(midonet_uri=midonet_uri,
                                       keystone_tokens_endpoint=keystone_tokens_endpoint,
                                       username=admin_user, password=admin_password, 
                                       tenant_name=self.admin_tenant)

        # See if the provider tenant and router exist. If not, create them.
        try:
            self.mido_conn.tenants().get(self.admin_tenant)
        except exc.HTTPNotFound:
            LOG.debug('Admin tenant(%r) not found. Creating...' % self.admin_tenant)
            self.mido_conn.tenants().create(self.admin_tenant)
        try:
            self.mido_conn.routers().get(self.admin_tenant, self.provider_router_id)
        except LookupError as e:
            LOG.debug('Provider router(%r) not found. Creating...' % self.provider_router_id)
            self.mido_conn.routers().create(self.admin_tenant, 
                             self.provider_router_name, self.provider_router_id)

    def get_all_networks(self, tenant_id, filter_opts=None):
        """
        Returns a dictionary containing all
        <network_uuid, network_name> for
        the specified tenant.
        """
        LOG.debug("get_all_networks() called with tenant_id %r", tenant_id)

        dummy_network = {'net-id': "fake-network",
                'net-name': "fake-name",
                'net-op-status': OperationalStatus}
        return [dummy_network]

    def create_network(self, tenant_id, net_name, **kwargs):
        """
        Creates a new Virtual Network, and assigns it
        a symbolic name.
        """
        LOG.debug("create_network() called, tenant_id: %r, net_name: %r", 
                    tenant_id, net_name)
        LOG.debug("                            kwargs: %r", kwargs)

        try:
            self.mido_conn.tenants().get(tenant_id)

        except exc.HTTPNotFound:
            LOG.debug("Creating tenant: %r", tenant_id)
            self.mido_conn.tenants().create(tenant_id)
        except Exception as e:
            LOG.debug("Create tenant in midonet got exception: %r", e)
            raise e

        tenant_router_name = self.tenant_router_name_format % tenant_id
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
            response, content = self.mido_conn.routers().create(
                                    tenant_id, tenant_router_name)
            response, content = self.mido_conn.get(
                                    response['location'])
            tenant_router_id = content['id']
            
            # Create a link from the provider router
            # TODO: might as well remove hardcoded addresses and length
            response, content = self.mido_conn.routers().link_router_create(
                                        self.admin_tenant,
                                        self.provider_router_id,
                                        '10.0.0.0', 30,
                                        '10.0.0.1', '10.0.0.2', 
                                        tenant_router_id)

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
        LOG.debug("delete_network() called. tenant_id: %r, net_id: %r", tenant_id, net_id)

        tenant_router_name = self.tenant_router_name_format % tenant_id
        LOG.debug("Midonet Tenant Router Name: %r", tenant_router_name)
        # do get routers to see if the tenant already has its tenant router.
        response, content = self.mido_conn.routers().list(tenant_id)

        tenant_router_id = None
        for r in content:
            if r['name'] == tenant_router_name:
                LOG.debug("Tenant Router found")
                tenant_router_id = r['id']

        # Delete link between the tenant router and the bridge 
        try:
            response, content = self.mido_conn.routers().link_bridge_delete(
                                                     tenant_id, tenant_router_id, net_id)
        except Exception as e:
            LOG.debug("Delete link got an exception: %r. Keep going.", e)
            pass

        # Delete the bridge
        try:
            response, content = self.mido_conn.bridges().delete(tenant_id, net_id)
        except Exception as e:
            LOG.debug("Delete bridge got an exception: %r. Keep going.", e)
            pass


    def get_network_details(self, tenant_id, net_id):
        """
        Deletes the Virtual Network belonging to a the
        spec
        """
        LOG.debug("get_network_details() called\n")

    def update_network(self, tenant_id, net_id, **kwargs):
        LOG.debug("update_network() called")

    def get_all_ports(self, tenant_id, net_id, **kwargs):
        """
        Retrieves all port identifiers belonging to the
        specified Virtual Network.
        """
        LOG.debug("get_all_ports() called: tenant_id: %r, net_id:%r, kwargs:%r", tenant_id, net_id, kwargs)
        return []

    def create_port(self, tenant_id, net_id, **kwargs):
        """
        Creates a port on the specified Virtual Network.
        """
        LOG.debug("create_port() called\n")

    def delete_port(self, tenant_id, net_id, port_id):
        """
        Deletes a port on a specified Virtual Network,
        if the port contains a remote interface attachment,
        the remote interface is first un-plugged and then the port
        is deleted.
        """
        LOG.debug("delete_port() called\n")

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
        LOG.debug("get_port_details() called\n")

    def plug_interface(self, tenant_id, net_id, port_id, remote_interface_id):
        """
        Attaches a remote interface to the specified port on the
        specified Virtual Network.
        """
        LOG.debug("plug_interface() called\n")

    def unplug_interface(self, tenant_id, net_id, port_id):
        """
        Detaches a remote interface from the specified port on the
        specified Virtual Network.
        """
        LOG.debug("unplug_interface() called\n")

    supported_extension_aliases = ["FOXNSOX"]

    def method_to_support_foxnsox_extension(self):
        LOG.debug("method_to_support_foxnsox_extension() called\n")


