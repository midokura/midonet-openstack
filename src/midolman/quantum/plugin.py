# Copyright (C) 2012 Midokura Japan K.K. 
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
# @author: Takaaki Suzuki Midokura Japan KK

import logging
import ConfigParser
from midonet.client.mgmt import MidonetMgmt
from midonet.client.web_resource import WebResource
from midonet.auth.keystone import KeystoneAuth
from quantum.db import db_base_plugin_v2
from quantum.db import api as db
from quantum.db import models_v2
from quantum.api.v2 import attributes
from quantum.common.utils import find_config_file
from quantum.common import exceptions as q_exc

LOG = logging.getLogger('MidoNetPlugin')
LOG.setLevel(logging.DEBUG)

class MidoNetPluginV2(db_base_plugin_v2.QuantumDbPluginV2):

    def __init__(self):
        # Read plugin config file
        config = ConfigParser.RawConfigParser()
        config_file = find_config_file({"plugin":"midonet"},
                                        "midonet_plugin.ini")
        if not config_file:
            raise Exception("Configuration file %s doesn't exist" %
                            "midonet_plugin.ini")
        config.read(config_file)

        # add keystone auth
        admin_pass = config.get('keystone', 'admin_password')
        keystone_uri = config.get('keystone', 'keystone_uri')
        auth = KeystoneAuth(uri=keystone_uri,
                            username='admin', password=admin_pass,
                            tenant_name='admin')
        web_resource = WebResource(auth, logger=LOG)
        # Create MidoNetClient
        self.mido_mgmt = MidonetMgmt(web_resource=web_resource, logger=LOG)

        # Create sql connection
        sql_connection = config.get('mysql', 'sql_connection')
        sql_max_retries = config.get('mysql', 'sql_max_retries')
        LOG.debug("sql_connection %r", sql_connection)
        LOG.debug("sql_max_retries %r", sql_max_retries)

        options = {
            'sql_connection': sql_connection,
            'sql_max_retries': sql_max_retries,
            'base': models_v2.model_base.BASEV2,
        }
        db.configure_db(options)

    def create_subnet(self, context, subnet):
        """
        Create DHCP entry for bridge of MidoNet
        """
        if subnet['subnet']['ip_version'] == 6:
            raise q_exc.NotImplementedError(message="MidoNet doesn't support IPv6")
        network_address, prefix = subnet['subnet']['cidr'].split('/')
        session = context.session
        with session.begin(subtransactions=True):
            sub = super(MidoNetPluginV2, self).create_subnet(context, subnet)
            bridges = self.mido_mgmt.get_bridges(
                    {'tenant_id':subnet['subnet']['tenant_id']})
            gateway_ip = sub['gateway_ip']
            for b in bridges:
                found = False
                if b.get_id() == sub['network_id']:
                      b.add_dhcp_subnet().default_gateway(
                          gateway_ip).subnet_prefix(
                          network_address).subnet_length(prefix).create()
                      found = True
                      break
            if not found:
                raise Exception("Databases are out of Sync.")
        return sub

    def get_subnet(self, context, id, fields=None):
        """
        Get midonet bridge information.
        """
        subnet = super(MidoNetPluginV2, self).get_subnet(context, id)
        bridges = self.mido_mgmt.get_bridges({'tenant_id':context.tenant_id})
        network_address, prefix = subnet['cidr'].split('/')
        found = False
        for b in bridges:
            if b.get_id() == subnet['network_id']:
                dhcp = b.get_dhcp_subnets()
                b_network_address = dhcp[0].get_subnet_prefix()
                b_prefix = dhcp[0].get_subnet_length()
                if network_address == b_network_address and int(prefix) == b_prefix:
                    found = True
        if not found:
            raise Exception("Databases are out of Sync.")
        return subnet

    def get_subnets(self, context, filters=None, fields=None):
        """
        List midonet bridge information.
        """
        subnet = super(MidoNetPluginV2, self).get_subnets(context, filters, fields)
        bridges = self.mido_mgmt.get_bridges({'tenant_id':context.tenant_id})
        for sub in subnet:
            network_address, prefix = sub['cidr'].split('/')
            found = False
            for b in bridges:
                if b.get_id() == sub['network_id']:
                    dhcp = b.get_dhcp_subnets()
                    b_network_address = dhcp[0].get_subnet_prefix()
                    b_prefix = dhcp[0].get_subnet_length()
                    if network_address == b_network_address and int(prefix) == b_prefix:
                        found = True
            if not found:
                raise Exception("Databases are out of Sync.")
        return subnet

    def delete_subnet(self, context, id):
        """
        Delete midonet bridge
        """
        session = context.session
        with session.begin(subtransactions=True):
            sub = super(MidoNetPluginV2, self).get_subnet(context, id, fields=None)
            bridges = self.mido_mgmt.get_bridges({'tenant_id':context.tenant_id})
            for b in bridges:
                if b.get_id() == sub['network_id']:
                    dhcp = b.get_dhcp_subnets()
                    network_address = dhcp[0].get_subnet_prefix()
                    prefix = dhcp[0].get_subnet_length()
                    gateway_ip = sub['gateway_ip']
                    dhcp[0].default_gateway(
                        gateway_ip).subnet_prefix(
                        network_address).subnet_length(prefix).delete()
                    break
            sub = super(MidoNetPluginV2, self).delete_subnet(context, id)

    def create_network(self, context, network):
        """
        Create bridge of midonet
        """
        session = context.session
        with session.begin(subtransactions=True):
            bridge = self.mido_mgmt.add_bridge().name(
                 network['network']['name']).tenant_id(
                             context.tenant_id).create()
            network['network']['id'] = bridge.get_id()
            net = super(MidoNetPluginV2, self).create_network(context, network)
        return net

    def update_network(self, context, id, network):
        """
        Update bridge name
        """
        session = context.session
        with session.begin(subtransactions=True):
            net = super(MidoNetPluginV2, self).update_network(
                                              context, id, network)
            bridges = self.mido_mgmt.get_bridges(
                    {'tenant_id':context.tenant_id})
            found = False
            for b in bridges:
                if net['id'] == b.get_id():
                    b.name(net['name']).update()
                    found = True
                    break
            if not found:
                raise Exception("Databases are out of Sync.")
        return net

    def get_network(self, context, id, fields=None):
        """
        Get a bridge of midonet
        """
        found = False
        net = super(MidoNetPluginV2, self).get_network(context, id, None)
        bridges = self.mido_mgmt.get_bridges({'tenant_id':context.tenant_id})
        for b in bridges:
            if b.get_id() == net['id'] and b.get_name() == net['name']:
               found = True
               break
        if not found:
           raise Exception("Databases are out of Sync.")
        return net

    def get_networks(self, context, filters=None, fields=None):
        """
        List bridge of midonet
        """
        net = super(MidoNetPluginV2, self).get_networks(context, filters, None)
        bridges = self.mido_mgmt.get_bridges({'tenant_id':context.tenant_id})
        for n in net:
            found = False
            for b in bridges:
                if n['id'] == b.get_id() and n['name'] == b.get_name():
                    found = True
            if not found:
               raise Exception("Databases are out of Syc.")
        return net

    def delete_network(self, context, id):
        """
        Delete a bridge of midonet.
        """
        session = context.session
        with session.begin(subtransactions=True):
            net = super(MidoNetPluginV2, self).get_network(context, id, None)
            bridges = self.mido_mgmt.get_bridges({'tenant_id':context.tenant_id})
            super(MidoNetPluginV2, self).delete_network(context, id)
            found = False
            for b in bridges:
                if b.get_name() == net['name']:
                   b.delete()
                   found = True
                   break
            if not found:
                raise Exception("Databases are out of Sync.")

    def create_port(self, context, port):
        """
        Create port for Midonet bridge
        """
        session = context.session
        with session.begin(subtransactions=True):
            bridges = self.mido_mgmt.get_bridges({'tenant_id':context.tenant_id})
            found = False
            for b in bridges:
                if b.get_id() == port['port']['network_id']:
                    mido_port = b.add_materialized_port().create()
                    found = True
                    break
            if not found:
                raise Exception("Database are out of Sync")
            port['port']['id'] = mido_port.get_id()
            p = super(MidoNetPluginV2, self).create_port(context, port)
        return p

    def update_port(self, context, id, port):
        """
        Update port
        """
        return super(MidoNetPluginV2, self).update_port(context, id, port)

    def get_port(self, context, id, fields=None):
        """
        Retrieve a port.
        """
        port = super(MidoNetPluginV2, self).get_port(context, id, fields)
        bridges = self.mido_mgmt.get_bridges({'tenant_id':context.tenant_id})
        found = False
        for b in bridges:
            if port['network_id'] == b.get_id():
                b_ports = b.get_ports()
                for p in b_ports:
                    if port['id'] == p.get_id():
                        found = True
        if not found:
            raise Exception("Databases are out of Sync.")
        return port

    def get_ports(self, context, filters=None, fields=None):
        """
        List port
        """
        ports = super(MidoNetPluginV2, self).get_ports(context, filters)
        bridges = self.mido_mgmt.get_bridges({'tenant_id':context.tenant_id})
        for port in ports:
            found = False
            for b in bridges:
                if port['network_id'] == b.get_id():
                    b_ports = b.get_ports()
                    for p in b_ports:
                        if port['id'] == p.get_id():
                            found = True
            if not found:
               raise Exception("Databases are out of Sync.")
        return ports

    def delete_port(self, context, id):
        """
        Delete a port.
        """
        session = context.session
        with session.begin(subtransactions=True):
            port = super(MidoNetPluginV2, self).get_port(context, id, None)
            bridges = self.mido_mgmt.get_bridges({'tenant_id':context.tenant_id})
            found = False
            for b in bridges:
                if b.get_id() == port['network_id']:
                    bridge_port = b.get_ports()
                    for bp in bridge_port:
                        if bp.get_id() == id:
                            bp.delete()
                            found = True
                            break
            if not found:
                raise Exception("Databases are out of Sync.")
            port = super(MidoNetPluginV2, self).delete_port(context, id)
        return port
