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
from quantum.db import db_base_plugin_v2
from quantum.db import l3_db
from quantum.db import api as db
from quantum.db import models_v2
from quantum.api.v2 import attributes
from quantum.common.utils import find_config_file
from quantum.common import exceptions as q_exc

from midonet.client.mgmt import MidonetMgmt
from midonet.client.web_resource import WebResource
from midonet.auth.keystone import KeystoneAuth
from webob import exc as w_exc



LOG = logging.getLogger('MidonetPluginV2')
LOG.setLevel(logging.DEBUG)

class MidonetResourceNotFound(q_exc.NotFound):
    message = _('MidoNet %(resource_type)s %(id)s could not be found')

class MidonetPluginV2(db_base_plugin_v2.QuantumDbPluginV2,
                      l3_db.L3_NAT_db_mixin):

    supported_extension_aliases = ['router']

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
        admin_user = config.get('keystone', 'quantum_admin_username')
        admin_pass = config.get('keystone', 'quantum_admin_password')
        admin_tenant_name = config.get('keystone', 'quantum_admin_tenant_name')
        keystone_uri = config.get('keystone', 'quantum_admin_auth_url')
        auth = KeystoneAuth(uri=keystone_uri,
                            username=admin_user, password=admin_pass,
                            tenant_name=admin_tenant_name)
        web_resource = WebResource(auth, logger=LOG)
        # Create MidoNet Management API wrapper object.
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
                bridge = self.mido_mgmt.get_bridge(sn_entry['network_id'])
            except HTTPError as e:
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

        qsubnet = super(MidonetPluginV2, self).get_subnet(context, id)
        mbridge_id = qsubnet['network_id']
        try:
            bridge = self.mido_mgmt.get_bridge(mbridge_id)
        except w_exc.HTTPNotFound as e:
            raise MidonetResourceNotFound(resource_type='Bridge',
                                          id=mbridge_id)

        # get dhcp subnet data from MidoNet bridge.
        dhcps = bridge.get_dhcp_subnets()
        b_network_address = dhcps[0].get_subnet_prefix()
        b_prefix = dhcps[0].get_subnet_length()

        # Validate against quantum database.
        network_address, prefix = qsubnet['cidr'].split('/')
        if network_address != b_network_address or int(prefix) != b_prefix:
            raise MidonetResourceNotFound(resource_type='DhcpSubnet',
                                          id=qsubnet['cidr'])
        return qsubnet

    def get_subnets(self, context, filters=None, fields=None):
        """
        List subnets from DB and verify with MidoNet API.
        """
        LOG.debug('context=%r, filters=%r, fields=%r', context.to_dict(),
                  filters, fields)
        subnets = super(MidonetPluginV2, self).get_subnets(context, filters,
                                                           fields)

        for sn in subnets:
            try:
                bridge = self.mido_mgmt.get_bridge(sn['network_id'])
            except w_exc.HTTPNotFound as e:
                raise MidonetResourceNotFound(resource_type='Bridge',
                                              id=sn['network_id'])

            # TODO: dedupe this part.
            # get dhcp subnet data from MidoNet bridge.
            dhcps = bridge.get_dhcp_subnets()
            b_network_address = dhcps[0].get_subnet_prefix()
            b_prefix = dhcps[0].get_subnet_length()

            # Validate against quantum database.
            if sn.get('cidr'):
                network_address, prefix = sn['cidr'].split('/')
                if network_address != b_network_address or \
                        int(prefix) != b_prefix:
                    raise MidonetResourceNotFound(resource_type='DhcpSubnet',
                                          id=sn['cidr'])
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
                bridge = self.mido_mgmt.get_bridge(subnet['network_id'])
            except w_exc.HTTPNotFound as e:
                raise MidonetResourceNotFound(resource_type='Bridge',
                                              id=subnet['network_id'])

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
                bridge = self.mido_mgmt.get_bridge(id)
            except w_exc.HTTPNotFound as e:
                raise MidonetResourceNotFound(resource_type='Bridge', id=id)
            bridge.name(net['name']).update()
        return net

    def get_network(self, context, id, fields=None):
        """
        Get and return requested quantum network from DB and verify
        that it exists in MidoNet.
        """
        LOG.debug('context=%r, id=%r, fields=%r', context.to_dict(), id,
                  fields)

        qnet = super(MidonetPluginV2, self).get_network(context, id, fields)
        try:
            bridge = self.mido_mgmt.get_bridge(id)
        except w_exc.HTTPNotFound as e:
            raise MidonetResourceNotFound(resource_type='Bridge', id=id)
        return qnet

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
                bridge = self.mido_mgmt.get_bridge(n['id'])
            except w_exc.HTTPNotFound as e:
                raise MidonetResourceNotFound(resource_type='Bridge',
                                              id=n['id'])
        return net

    def delete_network(self, context, id):
        """
        Delete a network and its corresponding MidoNet bridge.
        """
        LOG.debug('context=%r, id=%r', context.to_dict(), id)

        with session.begin(subtransactions=True):
            self.mido_mgmt.get_bridge(id).delete()
            super(MidonetPluginV2, self).delete_network(context, id)

    def create_port(self, context, port):
        """
        Create a port in DB and its corresponding port on the MidoNet bridge.
        """
        LOG.debug('context=%r, port=%r', context.to_dict(), port)

        is_router_interface = False
        port_data = port['port']
        # get the bridge and create a port on it.
        try:
            bridge = self.mido_mgmt.get_bridge(port_data['network_id'])
        except w_exc.HTTPNotFound as e:
            raise MidonetResourceNotFound(resource_type='Bridge',
                                          id=port_data['network_id'])

        if port_data['device_owner'] == l3_db.DEVICE_OWNER_ROUTER_INTF:
            is_router_interface = True

        if is_router_interface:
            bridge_port = bridge.add_interior_port().create()
        else:
            bridge_port = bridge.add_exterior_port().create()

        # set midonet port id to quantum port id and create a DB record.
        port_data['id'] = bridge_port.get_id()
        qport = super(MidonetPluginV2, self).create_port(context, port)

        if not is_router_interface:
            # get ip and mac from DB record.
            fixed_ip = qport['fixed_ips'][0]['ip_address']
            mac = qport['mac_address']

            # create dhcp host entry under the bridge.
            dhcp_subnets = bridge.get_dhcp_subnets()
            if len(dhcp_subnets) > 0:
                dhcp_subnets[0].add_dhcp_host().ip_addr(fixed_ip)\
                                               .mac_addr(mac)\
                                               .create()
        return qport

    def update_port(self, context, id, port):
        """
        Update port.
        Note: Nothing to do with MidoNet?
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
            bridge_port = self.mido_mgmt.get_port(id)
        except w_exc.HTTPNotFound as e:
            raise MidonetResourceNotFound(resource_type='Port', id=id)
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
                for port in qports:
                    self.mido_mgmt.get_port(port['id'])
            except w_exc.HTTPNotFound as e:
                raise MidonetResourceNotFound(resource_type='Port',
                                              id=port['id'])
        return qports

    def delete_port(self, context, id, l3_port_check=True):
        """
        Delete a quantum port and corresponding MidoNet bridge port.
        """
        # if needed, check to see if this is a port owned by
        # and l3-router.  If so, we should prevent deletion.
        if l3_port_check:
            self.prevent_l3_port_deletion(context, id)

        session = context.session
        with session.begin(subtransactions=True):
            qport = super(MidonetPluginV2, self).get_port(context, id, None)
            bridge = self.mido_mgmt.get_bridge(qport['network_id'])
            # get ip and mac from DB record.
            fixed_ip = qport['fixed_ips'][0]['ip_address']
            mac = qport['mac_address']

            # create dhcp host entry under the bridge.
            dhcp_subnets = bridge.get_dhcp_subnets()
            if len(dhcp_subnets) > 0:
                for dh in dhcp_subnets[0].get_dhcp_hosts():
                    if dh.get_mac_addr() == mac and \
                            dh.get_ip_addr() == fixed_ip:
                        dh.delete()

            self.mido_mgmt.get_port(id).delete()
            qport = super(MidonetPluginV2, self).delete_port(context, id)
        return qport

    #
    # L3 APIs.
    #

    def create_router(self, context, router):
        LOG.debug('create_router: context=%r, router=%r', context.to_dict(),
                  router)

        if router['router']['admin_state_up'] is False:
            LOG.warning('Ignoreing admin_state_up=False for router=%r',
                        router)

        tenant_id = self._get_tenant_id_for_create(context, router['router'])
        session = context.session
        with session.begin(subtransactions=True):
            mrouter = self.mido_mgmt.add_router()\
                         .name(router['router']['name'])\
                         .tenant_id(tenant_id).create()
            qrouter = super(MidonetPluginV2, self).create_router(context,
                                                                 router)
            # get entry from the DB and update 'id' with MidoNet router id.
            qrouter_entry = self._get_router(context, qrouter['id'])
            qrouter['id'] = mrouter.get_id()
            qrouter_entry.update(qrouter)
            return qrouter

    def update_router(self, context, id, router):
        LOG.debug('update_router: context=%r, id=%r, router=%r',
                  context.to_dict(), id, router)

        if router['router'].get('admin_state_up') is False:
            raise q_exc.NotImplementedError('admin_state_up=False '
                                                'routers are not '
                                                'supported.')

        changed_name = router['router'].get('name')

        try:
            if changed_name:
                self.mido_mgmt.get_router(id)\
                              .name(changed_name).update()
            qrouter = super(MidonetPluginV2, self).update_router(context, id,
                                                                 router)
        except Exception as e:
            LOG.error('Either MidoNet API or DB for update router failed.')
            raise e
        return qrouter

    def delete_router(self, context, id):
        LOG.debug('delete_router: context=%r, id=%r', context.to_dict(), id)

        result =  super(MidonetPluginV2, self).delete_router(context, id)
        self.mido_mgmt.get_router(id).delete()
        return result

    def get_router(self, context, id, fields=None):
        LOG.debug('get_router: context=%r, id=%r, fields=%r',
                  context.to_dict(), id, fields)
        qrouter = super(MidonetPluginV2, self).get_router(context, id, fields)

        try:
            self.mido_mgmt.get_router(id)
        except w_exc.HTTPNotFound as e:
           raise MidonetResourceNotFound(resource_type='Router', id=id)

        return qrouter

    def get_routers(self, context, filters=None, fields=None):
        LOG.debug('get_routers: context=%r, flters=%r, fields=%r',
                  context.to_dict(), filters, fields)

        qrouters = super(MidonetPluginV2, self).get_routers(context,
                             filters, fields)
        for qr in qrouters:
            try:
                self.mido_mgmt.get_router(qr['id'])
            except w_exc.HTTPNotFound as e:
                raise MidonetResourceNotFound(resource_type='Router',
                                              id=qr['id'])
        return qrouters


    def add_router_interface(self, context, router_id, interface_info):

        qport = super(MidonetPluginV2, self).add_router_interface(context,
                router_id, interface_info)

        if 'subnet_id' in interface_info:
            subnet_id = interface_info['subnet_id']
            subnet = self._get_subnet(context, subnet_id)

            gateway_ip = subnet['gateway_ip']
            network_address, length = subnet['cidr'].split('/')

            # Link the router and the bridge port.
            mrouter = self.mido_mgmt.get_router(router_id)
            mrouter_port = mrouter.add_interior_port().port_address(gateway_ip)\
                                 .network_address(network_address)\
                                 .network_length(length)\
                                 .create()
            mbridge_port = self.mido_mgmt.get_port(qport['port_id'])
            mrouter_port.link(mbridge_port.get_id())

            # Add a route entry to the subnet
            mrouter.add_route().type('Normal')\
                               .src_network_addr('0.0.0.0')\
                               .src_network_length(0)\
                               .dst_network_addr(network_address)\
                               .dst_network_length(length)\
                               .weight(100)\
                               .next_hop_port(mrouter_port.get_id())\
                               .create()
        return qport
