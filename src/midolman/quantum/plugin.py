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

import logging
from quantum.quantum_plugin_base import QuantumPluginBase

LOG = logging.getLogger('midolman.quantum.plugins.MidonetPlugin')


class MidonetPlugin(QuantumPluginBase):

    """
    This is a skeleton that is copied from QuantumEchoPlugin in SamplePlugin.
    """

    def get_all_networks(self, tenant_id):
        """
        Returns a dictionary containing all
        <network_uuid, network_name> for
        the specified tenant.
        """
        print("get_all_networks() called\n")

    def create_network(self, tenant_id, net_name, **kwargs):
        """
        Creates a new Virtual Network, and assigns it
        a symbolic name.
        """
        print("create_network() called\n")

    def delete_network(self, tenant_id, net_id):
        """
        Deletes the network with the specified network identifier
        belonging to the specified tenant.
        """
        print("delete_network() called\n")

    def get_network_details(self, tenant_id, net_id):
        """
        Deletes the Virtual Network belonging to a the
        spec
        """
        print("get_network_details() called\n")

    def update_network(self, tenant_id, net_id, **kwargs):
        print("update_network() called")

    def get_all_ports(self, tenant_id, net_id):
        """
        Retrieves all port identifiers belonging to the
        specified Virtual Network.
        """
        print("get_all_ports() called\n")

    def create_port(self, tenant_id, net_id, **kwargs):
        """
        Creates a port on the specified Virtual Network.
        """
        print("create_port() called\n")

    def delete_port(self, tenant_id, net_id, port_id):
        """
        Deletes a port on a specified Virtual Network,
        if the port contains a remote interface attachment,
        the remote interface is first un-plugged and then the port
        is deleted.
        """
        print("delete_port() called\n")

    def update_port(self, tenant_id, net_id, port_id, **kwargs):
        """
        Updates the attributes of a port on the specified Virtual Network.
        """
        print("update_port() called\n")

    def get_port_details(self, tenant_id, net_id, port_id):
        """
        This method allows the user to retrieve a remote interface
        that is attached to this particular port.
        """
        print("get_port_details() called\n")

    def plug_interface(self, tenant_id, net_id, port_id, remote_interface_id):
        """
        Attaches a remote interface to the specified port on the
        specified Virtual Network.
        """
        print("plug_interface() called\n")

    def unplug_interface(self, tenant_id, net_id, port_id):
        """
        Detaches a remote interface from the specified port on the
        specified Virtual Network.
        """
        print("unplug_interface() called\n")

    supported_extension_aliases = ["FOXNSOX"]

    def method_to_support_foxnsox_extension(self):
        print("method_to_support_foxnsox_extension() called\n")


