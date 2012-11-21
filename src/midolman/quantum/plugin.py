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
# @author: Tomoe Sugihara Midokura Japan KK

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

LOG = logging.getLogger('MidonetPluginV2')
LOG.setLevel(logging.DEBUG)

class MidonetPluginV2(db_base_plugin_v2.QuantumDbPluginV2):

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
        LOG.debug('context=%r, subnet=%r', context.to_dict(), subnet)

        if subnet['subnet']['ip_version'] == 6:
            raise q_exc.NotImplementedError('MidoNet doesn\'t support IPv6.')

        net = super(MidonetPluginV2, self).get_network(context,
                                           subnet['subnet']['network_id'],
                                           fields=None)
        if net['subnets']:
            raise q_exc.NotImplementedError(
                    'MidoNet doesn\'t support multiple subnets '
                    'on the same network.')

        session = context.session
        with session.begin(subtransactions=True):
            sn_entry = super(MidonetPluginV2, self).create_subnet(context,
                             subnet)

            try:
                bridge = self.mido_mgmt.get_bridge(sn_entry['tenant_id'],
                                                   sn_entry['network_id'])
            except LookupError as e:
                raise q_exc.NetworkNotFound(net_id=subnet['network_id'])

            gateway_ip = subnet['subnet']['gateway_ip']
            network_address, prefix = subnet['subnet']['cidr'].split('/')
            bridge.add_dhcp_subnet().default_gateway(gateway_ip)\
                                    .subnet_prefix(network_address)\
                                    .subnet_length(prefix).create()
        return sn_entry

    def get_subnet(self, context, id, fields=None):
        """
        Get midonet bridge information.
        """
        LOG.debug('context=%r, id=%r, fields=%r', context.to_dict(), id,
                  fields)

        subnet = super(MidonetPluginV2, self).get_subnet(context, id)
        try:
            bridge = self.mido_mgmt.get_bridge(subnet['tenant_id'],
                                               subnet['network_id'])
        except LookupError as e:
            raise Exception("Databases are out of Sync.")

        # get dhcp subnet data from MidoNet bridge.
        dhcps = bridge.get_dhcp_subnets()
        b_network_address = dhcps[0].get_subnet_prefix()
        b_prefix = dhcps[0].get_subnet_length()

        # Validate against quantum database.
        network_address, prefix = subnet['cidr'].split('/')
        if network_address != b_network_address or int(prefix) != b_prefix:
            raise Exception("Databases are out of Sync.")
        return subnet

    def get_subnets(self, context, filters=None, fields=None):
        """
        List subnets from DB and verify with MidoNet API.
        """
        LOG.debug('context=%r, filters=%r, fields=%r', context.to_dict(), filters, fields)
        subnets = super(MidonetPluginV2, self).get_subnets(context, filters, fields)

        for sn in subnets:
            try:
                bridge = self.mido_mgmt.get_bridge(sn['tenant_id'],
                                                   sn['network_id'])
            except LookupError as e:
                raise Exception("Databases are out of Sync.")

            # TODO: dedupe this part.
            # get dhcp subnet data from MidoNet bridge.
            dhcps = bridge.get_dhcp_subnets()
            b_network_address = dhcps[0].get_subnet_prefix()
            b_prefix = dhcps[0].get_subnet_length()

            # Validate against quantum database.
            network_address, prefix = sn['cidr'].split('/')
            if network_address != b_network_address or int(prefix) != b_prefix:
                raise Exception("Databases are out of Sync.")
        return subnets

    def delete_subnet(self, context, id):
        """
        Delete quantum network and its corresponding MidoNet bridge.
        """
        session = context.session
        with session.begin(subtransactions=True):
            subnet = super(MidonetPluginV2, self).get_subnet(context, id,
                                                             fields=None)
            try:
                bridge = self.mido_mgmt.get_bridge(subnet['tenant_id'],
                                                   subnet['network_id'])
            except LookupError as e:
                raise Exception("Databases are out of Sync.")

            dhcp = bridge.get_dhcp_subnets()
            dhcp[0].delete()
            sub = super(MidonetPluginV2, self).delete_subnet(context, id)

    def create_network(self, context, network):
        """
        Create a MidoNet bridge and a DB entry.
        """
        LOG.debug('context=%r, network=%r', context.to_dict(), network)

        if network['network']['admin_state_up'] is False:
            LOG.warning('Ignoreing admin_state_up=False for network=%r',
                        network)

        tenant_id = self._get_tenant_id_for_create(context, network['network'])
        session = context.session
        with session.begin(subtransactions=True):
            bridge = self.mido_mgmt.add_bridge()\
                         .name(network['network']['name'])\
                         .tenant_id(tenant_id).create()

            # Set MidoNet bridge ID to the quantum DB entry
            network['network']['id'] = bridge.get_id()
            net = super(MidonetPluginV2, self).create_network(context, network)
        return net

    def update_network(self, context, id, network):
        """
        Update network and its corresponding MidoNet bridge.
        """
        LOG.debug('context=%r, id=%r, network=%r', context.to_dict(), id,
                  network)

        # Reject admin_state_up=False
        if network['network'].get('admin_state_up') and \
           network['network']['admin_state_up'] is False:
            raise q_exc.NotImplementedError('admin_state_up=False '
                                                'networks are not '
                                                'supported.')

        session = context.session
        with session.begin(subtransactions=True):
            net = super(MidonetPluginV2, self).update_network(
                                              context, id, network)
            try:
                bridge = self.mido_mgmt.get_bridge(context.tenant_id, id)
            except LookupError as e:
                raise q_exc.NetworkNotFound(net_id=id)
            bridge.name(net['name']).update()
        return net

    def get_network(self, context, id, fields=None):
        """
        Get and return requested quantum network from DB and verify
        that it exists in MidoNet.
        """
        LOG.debug('context=%r, id=%r, fields=%r', context.to_dict(), id,
                  fields)

        net = super(MidonetPluginV2, self).get_network(context, id, fields)
        try:
            bridge = self.mido_mgmt.get_bridge(context.tenant_id, id)
        except LookupError as e:
            raise q_exc.NetworkNotFound(net_id=id)
        return net

    def get_networks(self, context, filters=None, fields=None):
        """
        List quantum networks and verify that all exist in MidoNet.
        """
        LOG.debug('context=%r, filters=%r, fields=%r', context.to_dict(),
                  filters, fields)

        net = super(MidonetPluginV2, self).get_networks(context, filters, fields)
        bridges = self.mido_mgmt.get_bridges({'tenant_id':context.tenant_id})
        for n in net:
            try:
                bridge = self.mido_mgmt.get_bridge(context.tenant_id, n['id'])
            except LookupError as e:
               raise Exception("Databases are out of Syc.")
        return net

    def delete_network(self, context, id):
        """
        Delete a network and its corresponding MidoNet bridge.
        """
        LOG.debug('context=%r, id=%r', context.to_dict(), id)

        session = context.session
        with session.begin(subtransactions=True):
            self.mido_mgmt.get_bridge(context.tenant_id, id).delete()
            super(MidonetPluginV2, self).delete_network(context, id)

    def create_port(self, context, port):
        """
        Create a port in DB and its corresponding port on the MidoNet bridge.
        """
        LOG.debug('context=%r, port=%r', context.to_dict(), port)

        session = context.session
        with session.begin(subtransactions=True):
            # get the bridge and create a port on it.
            try:
                bridge = self.mido_mgmt.get_bridge(port['port']['tenant_id'],
                                                   port['port']['network_id'])
            except LookupError as e:
                raise q_exc.NetworkNotFound(net_id=port['port']['network_id'])

            bridge_port = bridge.add_materialized_port().create()

            # set midonet port id to quantum port id and create a DB record.
            port['port']['id'] = bridge_port.get_id()
            qport = super(MidonetPluginV2, self).create_port(context, port)

            # get ip and mac from DB record.
            fixed_ip = qport['fixed_ips'][0]['ip_address']
            mac =qport['mac_address']

            # create dhcp host entry under the bridge.
            dhcp_subnet = bridge.get_dhcp_subnets()[0]
            dhcp_subnet.add_dhcp_host().ip_addr(fixed_ip)\
                                       .mac_addr(mac)\
                                       .create()
        return qport

    def update_port(self, context, id, port):
        """
        Update port.
        TODO: Nothing to do with MidoNet?
        """
        LOG.debug('context=%r, id=%r, port=%r', context.to_dict(), id, port)
        return super(MidonetPluginV2, self).update_port(context, id, port)

    def get_port(self, context, id, fields=None):
        """
        Retrieve a port.
        """
        LOG.debug('context=%r, id=%r, fields=%r', context.to_dict(), id, fields)

        # get the quantum port from DB.
        qport = super(MidonetPluginV2, self).get_port(context, id, fields)

        # verify that corresponding port exists in MidoNet.
        try:
            LOG.debug('qport=%r', qport)
            bridge = self.mido_mgmt.get_bridge(qport['tenant_id'],
                                               qport['network_id'])
            #bridge_port = bridge.get_port(id)
        except LookupError as e:
            raise Exception("Databases are out of Sync.")

        return qport

    def get_ports(self, context, filters=None, fields=None):
        """
        List quantum ports and verify that they exist in MidoNet.
        """
        LOG.debug('context=%r, filters=%r, fields=%r', context.to_dict(),
                  filters, fields)
        qports = super(MidonetPluginV2, self).get_ports(context, filters,
                fields)
        LOG.debug('qport=%r', qports)

        #TODO: check if this methods is supposed to return all
        #      the ports across different bridges? if that's the case,
        #      we need to chenge the validation below.
        if len(qports) > 0:
            try:
                bridge = self.mido_mgmt.get_bridge(context.tenant_id,
                                                   qports[0]['network_id'])
                for port in qports:
                    bridge.get_port(port['id'])
            except LookupError as e:
                raise Exception("Databases are out of Sync.")

        return qports

    def delete_port(self, context, id):
        """
        Delete a port.
        """
        session = context.session
        with session.begin(subtransactions=True):
            qport = super(MidonetPluginV2, self).get_port(context, id, None)
            bridge = self.mido_mgmt.get_bridge(context.tenant_id,
                                               qport['network_id'])
            bridge.get_port(id).delete()

            qport = super(MidonetPluginV2, self).delete_port(context, id)
        return qport
