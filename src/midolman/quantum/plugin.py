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
from midolman.common.openstack import ChainManager, PortGroupManager
from webob import exc as w_exc


LOG = logging.getLogger('MidonetPluginV2')
LOG.setLevel(logging.DEBUG)

OS_TENANT_ROUTER_RULE_KEY = 'OS_TENANT_ROUTER_RULE'
OS_FLOATING_IP_RULE_KEY = 'OS_FLOATING_IP'
SNAT_RULE = 'SNAT'
SNAT_RULE_PROPERTY = {OS_TENANT_ROUTER_RULE_KEY: SNAT_RULE}


class MidonetResourceNotFound(q_exc.NotFound):
    message = _('MidoNet %(resource_type)s %(id)s could not be found')


class MidonetPluginV2(db_base_plugin_v2.QuantumDbPluginV2,
                      l3_db.L3_NAT_db_mixin):

    supported_extension_aliases = ['router']

    def __init__(self):
        # Read plugin config file
        config = ConfigParser.RawConfigParser()
        config_file = find_config_file({"plugin": "midonet"},
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

        # get token to save provider tenant id
        token = auth.get_token()
        self.provider_tenant_id = token.tenant['id']

        self.provider_router_name = config.get('midonet',
                                                'provider_router_name')
        self.metadata_router_name = config.get('midonet',
                                               'metadata_router_name')
        self.metadata_bridge_name = config.get('midonet',
                                               'metadata_bridge_name')

        if config.get('midonet', 'midonet_uri'):
            midonet_uri = config.get('midonet', 'midonet_uri')

        # Create MidoNet Management API wrapper object.
        client_logger = logging.getLogger('midonet.client')
        web_resource = WebResource(auth, logger=client_logger)
        self.mido_mgmt = MidonetMgmt(midonet_uri=midonet_uri,
                                     web_resource=web_resource, logger=LOG)

        self.chain_manager = ChainManager(self.mido_mgmt)
        self.pg_manager = PortGroupManager(self.mido_mgmt)

        # get MidoNet provider router
        self.provider_owned_routers = None
        self.provider_router = self._get_or_create_provider_router()

        # ensure metadata devices
        self.metadata_router = None
        self.metadata_bridge = None
        self._ensure_metadata_devices()

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
            except w_exc.HTTPNotFound as e:
                raise MidonetResourceNotFound(resource_type='Bridge',
                                              id=sn_entry['network_id'])

            gateway_ip = subnet['subnet']['gateway_ip']
            network_address, prefix = subnet['subnet']['cidr'].split('/')
            bridge.add_dhcp_subnet().default_gateway(gateway_ip)\
                                    .subnet_prefix(network_address)\
                                    .subnet_length(prefix).create()

            # If the network is externel, link the bridge to MidoNet provider
            # router
            self._extend_network_dict_l3(context, net)
            if net['router:external']:
                gateway_ip = sn_entry['gateway_ip']
                network_address, length = sn_entry['cidr'].split('/')

                # create a interior port in the MidoNet provider router
                pr_port = self.provider_router.add_interior_port()\
                        .port_address(gateway_ip)\
                        .network_address(network_address)\
                        .network_length(length)\
                        .create()

                # create a interior port in the bridge, then link
                # it to the provider router.
                br_port = bridge.add_interior_port().create()
                pr_port.link(br_port.get_id())

                # add a route for the subnet in the provider router
                self.provider_router.add_route().type('Normal')\
                                    .src_network_addr('0.0.0.0')\
                                    .src_network_length(0)\
                                    .dst_network_addr(network_address)\
                                    .dst_network_length(length)\
                                    .weight(100)\
                                    .next_hop_port(pr_port.get_id())\
                                    .create()
        return sn_entry

    def get_subnet(self, context, id, fields=None):
        """
        Get midonet bridge information.
        """
        LOG.debug('context=%r, id=%r, fields=%r', context.to_dict(), id,
                  fields)

        qsubnet = super(MidonetPluginV2, self).get_subnet(context, id)
        bridge_id = qsubnet['network_id']
        try:
            bridge = self.mido_mgmt.get_bridge(bridge_id)
        except w_exc.HTTPNotFound as e:
            raise MidonetResourceNotFound(resource_type='Bridge',
                                          id=bridge_id)

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
        subnet = super(MidonetPluginV2, self).get_subnet(context, id,
                                                         fields=None)
        net = super(MidonetPluginV2, self).get_network(context,
                                                       subnet['network_id'],
                                                       fields=None)
        bridge_id = subnet['network_id']
        try:
            bridge = self.mido_mgmt.get_bridge(bridge_id)
        except w_exc.HTTPNotFound as e:
            raise MidonetResourceNotFound(resource_type='Bridge', id=bridge_id)

        dhcp = bridge.get_dhcp_subnets()
        dhcp[0].delete()

        # If the network is externel, clean up routes, links, ports.
        self._extend_network_dict_l3(context, net)
        if net['router:external']:
            # Delete routes and unlink the router and the bridge.
            routes = self.provider_router.get_routes()

            bridge_ports_to_delete = []
            for p in self.provider_router.get_peer_ports():
                if p.get_device_id() == bridge.get_id():
                    bridge_ports_to_delete.append(p)

            for p in bridge.get_peer_ports():
                if p.get_device_id() == self.provider_router.get_id():
                    LOG.debug('unlinking/deleting provider router port=%r', p)
                    # delete the routes going to the birdge
                    for r in routes:
                        if r.get_next_hop_port() == p.get_id():
                            LOG.debug('Deleting route=%r', r)
                            r.delete()
                    p.unlink()
                    p.delete()

            # delete bridge port
            LOG.debug('deleting bridge port(s)=%r', bridge_ports_to_delete)
            map(lambda x: x.delete(), bridge_ports_to_delete)

        super(MidonetPluginV2, self).delete_subnet(context, id)

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

            # to handle l3 related data in DB
            self._process_l3_create(context, network['network'], net['id'])
            self._extend_network_dict_l3(context, net)
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
            #TODO: check if name has really been changed
            bridge.name(net['name']).update()

        self._extend_network_dict_l3(context, net)
        return net

    def get_network(self, context, id, fields=None):
        """
        Get and return requested quantum network from DB and verify
        that it exists in MidoNet.
        """
        LOG.debug('context=%r, id=%r, fields=%r', context.to_dict(), id,
                  fields)

        # NOTE: Get network data with all fields (fields=None) for
        #       _extend_network_dict_l3() method, which needs 'id' field
        qnet = super(MidonetPluginV2, self).get_network(context, id, None)
        try:
            bridge = self.mido_mgmt.get_bridge(id)
        except w_exc.HTTPNotFound as e:
            raise MidonetResourceNotFound(resource_type='Bridge', id=id)

        self._extend_network_dict_l3(context, qnet)
        return self._fields(qnet, fields)

    def get_networks(self, context, filters=None, fields=None):
        """
        List quantum networks and verify that all exist in MidoNet.
        """
        LOG.debug('context=%r, filters=%r, fields=%r', context.to_dict(),
                  filters, fields)

        # NOTE: Get network data with all fields (fields=None) for
        #       _extend_network_dict_l3() method, which needs 'id' field
        qnets = super(MidonetPluginV2, self).get_networks(context, filters,
                                                          None)
        bridges = self.mido_mgmt.get_bridges({'tenant_id': context.tenant_id})
        for n in qnets:
            try:
                bridge = self.mido_mgmt.get_bridge(n['id'])
            except w_exc.HTTPNotFound as e:
                raise MidonetResourceNotFound(resource_type='Bridge',
                                              id=n['id'])
            self._extend_network_dict_l3(context, n)

        qnets = self._filter_nets_l3(context, qnets, filters)
        return [self._fields(net, fields) for net in qnets]

    def delete_network(self, context, id):
        """
        Delete a network and its corresponding MidoNet bridge.
        """
        LOG.debug('context=%r, id=%r', context.to_dict(), id)

        self.mido_mgmt.get_bridge(id).delete()
        try:
            super(MidonetPluginV2, self).delete_network(context, id)
        except Exception as e:
            LOG.error('Failed to delete quantum db, while Midonet bridge=%r'
                      'had been deleted', id)
            raise e

    def create_port(self, context, port):
        """
        Create a port in DB and its corresponding port on the MidoNet bridge.
        """
        LOG.debug('context=%r, port=%r', context.to_dict(), port)

        is_router_interface = False
        is_compute_interface = False
        port_data = port['port']
        # get the bridge and create a port on it.
        try:
            bridge = self.mido_mgmt.get_bridge(port_data['network_id'])
        except w_exc.HTTPNotFound as e:
            raise MidonetResourceNotFound(resource_type='Bridge',
                                          id=port_data['network_id'])

        device_owner = port_data['device_owner']

        if device_owner.startswith('compute:') or device_owner is '':
            is_compute_interface = True
            bridge_port = bridge.add_exterior_port().create()
        elif device_owner == l3_db.DEVICE_OWNER_ROUTER_INTF:
            bridge_port = bridge.add_interior_port().create()
        elif device_owner == l3_db.DEVICE_OWNER_ROUTER_GW or \
                device_owner == l3_db.DEVICE_OWNER_FLOATINGIP:

            # This is a dummy port to make l3_db happy.
            # This will not be used in MidoNet
            bridge_port = bridge.add_interior_port().create()

        if bridge_port:
            LOG.debug('Created MidoNet bridge port=%r', bridge_port)
            # set midonet port id to quantum port id and create a DB record.
            port_data['id'] = bridge_port.get_id()

        session = context.session
        with session.begin(subtransactions=True):
            qport = super(MidonetPluginV2, self).create_port(context, port)
            if is_compute_interface:
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
        LOG.debug('context=%r, id=%r, fields=%r', context.to_dict(), id,
                  fields)

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

            chains = self.chain_manager.create_router_chains(tenant_id,
                                                             mrouter.get_id())

            # set chains to in/out filters
            mrouter.inbound_filter_id(chains['in'].get_id())\
                   .outbound_filter_id(chains['out'].get_id())\
                   .update()

            # get entry from the DB and update 'id' with MidoNet router id.
            qrouter_entry = self._get_router(context, qrouter['id'])
            qrouter['id'] = mrouter.get_id()
            qrouter_entry.update(qrouter)

            # link to metadata router
            mdr_port = self.metadata_router\
                           .add_interior_port()\
                           .network_address('169.254.255.0')\
                           .network_length(30)\
                           .port_address('169.254.255.1')\
                           .create()

            tr_port = mrouter.add_interior_port()\
                             .network_address('169.254.255.0')\
                             .network_length(30)\
                             .port_address('169.254.255.2')\
                             .create()
            mdr_port.link(tr_port.get_id())
            return qrouter

    def update_router(self, context, id, router):
        LOG.debug('update_router: context=%r, id=%r, router=%r',
                  context.to_dict(), id, router)

        if router['router'].get('admin_state_up') is False:
            raise q_exc.NotImplementedError('admin_state_up=False '
                                                'routers are not '
                                                'supported.')

        op_gateway_set = False
        op_gateway_clear = False

        # figure out which operation it is in
        if 'external_gateway_info' in router['router'] and \
                'network_id' in router['router']['external_gateway_info']:
            op_gateway_set = True
            external_net_id = \
                    router['router']['external_gateway_info']['network_id']
        elif 'external_gateway_info' in router['router'] and \
                router['router']['external_gateway_info'] == {}:
            op_gateway_clear = True

            qports = super(MidonetPluginV2, self).get_ports(context,
                {'device_id': [id],
                 'device_owner': ['network:router_gateway']})

            assert len(qports) == 1
            qport = qports[0]
            snat_ip = qport['fixed_ips'][0]['ip_address']
            bridge_id = qport['network_id']

        session = context.session
        with session.begin(subtransactions=True):

            qrouter = super(MidonetPluginV2, self).update_router(context, id,
                                                                 router)

            changed_name = router['router'].get('name')
            if changed_name:
                self.mido_mgmt.get_router(id).name(changed_name).update()

            tenant_router = self.mido_mgmt.get_router(id)
            if op_gateway_set:
                # find a qport with the network_id for the router
                qports = super(MidonetPluginV2, self).get_ports(context,
                    {'device_id': [id],
                     'device_owner': ['network:router_gateway']})
                assert len(qports) == 1
                qport = qports[0]
                snat_ip = qport['fixed_ips'][0]['ip_address']

                pr_port = self.provider_router\
                        .add_interior_port()\
                        .network_address('169.254.255.0')\
                        .network_length(30)\
                        .port_address('169.254.255.1')\
                        .create()

                LOG.debug('pr_port=%r', pr_port)

                # Create a port in the tenant router
                tr_port = tenant_router.add_interior_port()\
                                       .network_address('169.254.255.0')\
                                       .network_length(30)\
                                       .port_address('169.254.255.2')\
                                       .create()
                LOG.debug('tr_port=%r', tr_port)

                # Link them
                pr_port.link(tr_port.get_id())

                # Add a route for snat_ip to bring it down to tenant
                self.provider_router.add_route()\
                                    .type('Normal')\
                                    .src_network_addr('0.0.0.0')\
                                    .src_network_length(0)\
                                    .dst_network_addr(snat_ip)\
                                    .dst_network_length(32)\
                                    .weight(100)\
                                    .next_hop_port(pr_port.get_id())\
                                    .create()

                # Add default route to uplink in the tenant router
                tenant_router.add_route().type('Normal')\
                             .src_network_addr('0.0.0.0')\
                             .src_network_length(0)\
                             .dst_network_addr('0.0.0.0')\
                             .dst_network_length(0)\
                             .weight(100)\
                             .next_hop_port(tr_port.get_id())\
                             .create()

                # ADD SNAT(masquerade) rules
                chains = self.chain_manager.get_router_chains(
                        tenant_router.get_tenant_id(),
                        tenant_router.get_id())

                chains['in'].add_rule().nw_dst_address(snat_ip)\
                           .nw_dst_length(32)\
                           .type('rev_snat')\
                           .flow_action('accept')\
                           .in_ports([tr_port.get_id()])\
                           .properties(SNAT_RULE_PROPERTY)\
                           .position(1)\
                           .create()

                nat_targets = []
                nat_targets.append(
                    {'addressFrom': snat_ip, 'addressTo': snat_ip,
                     'portFrom': 1, 'portTo': 65535})

                chains['out'].add_rule().type('snat')\
                             .flow_action('accept')\
                             .nat_targets(nat_targets)\
                             .out_ports([tr_port.get_id()])\
                             .properties(SNAT_RULE_PROPERTY)\
                             .position(1)\
                             .create()

            if op_gateway_clear:
                # delete the port that is connected to provider router
                for p in tenant_router.get_ports():
                    if p.get_port_address() == '169.254.255.2':
                        peer_port_id = p.get_peer_id()
                        p.unlink()
                        self.mido_mgmt.get_port(peer_port_id).delete()
                        p.delete()

                # delete default route
                for r in tenant_router.get_routes():
                    if r.get_dst_network_addr() == '0.0.0.0' and \
                            r.get_dst_network_length() == 0:
                        LOG.debug('Deleting default route=%r', r)
                        r.delete()

                # delete SNAT(masquerade) rules
                chains = self.chain_manager.get_router_chains(
                        tenant_router.get_tenant_id(),
                        tenant_router.get_id())

                for r in chains['in'].get_rules():
                    if OS_TENANT_ROUTER_RULE_KEY in r.get_properties():
                        if r.get_properties()[OS_TENANT_ROUTER_RULE_KEY] == \
                                SNAT_RULE:
                            r.delete()

                for r in chains['out'].get_rules():
                    if OS_TENANT_ROUTER_RULE_KEY in r.get_properties():
                        if r.get_properties()[OS_TENANT_ROUTER_RULE_KEY] == \
                                SNAT_RULE:
                            r.delete()
        return qrouter

    def delete_router(self, context, id):
        LOG.debug('delete_router: context=%r, id=%r', context.to_dict(), id)

        mrouter = self.mido_mgmt.get_router(id)
        tenant_id = mrouter.get_tenant_id()
        mrouter.delete()

        # delete corresponding chains
        chains = self.chain_manager.get_router_chains(tenant_id,
                                                      mrouter.get_id())
        chains['in'].delete()
        chains['out'].delete()

        result = super(MidonetPluginV2, self).delete_router(context, id)
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

        # TODO: handle a case with 'port' in interface_info
        if 'subnet_id' in interface_info:
            subnet_id = interface_info['subnet_id']
            subnet = self._get_subnet(context, subnet_id)

            gateway_ip = subnet['gateway_ip']
            network_address, length = subnet['cidr'].split('/')

            # Link the router and the bridge port.
            mrouter = self.mido_mgmt.get_router(router_id)
            mrouter_port = mrouter.add_interior_port()\
                                  .port_address(gateway_ip)\
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

    def remove_router_interface(self, context, router_id, interface_info):
        """
        Remove interior ports that are on the router and the network
        specified in the request.
        """

        if 'port_id' in interface_info:
            LOG.error('adding interface with existing port is not supported. '
                      'Try doing it with subnet_id')
            raise q_exc.NotImplementedError()

        if 'subnet_id' in interface_info:

            subnet_id = interface_info['subnet_id']
            subnet = self._get_subnet(context, subnet_id)
            network_id = subnet['network_id']

            # find a quantum port for the network
            rport_qry = context.session.query(models_v2.Port)
            ports = rport_qry.filter_by(
                device_id=router_id,
                device_owner=l3_db.DEVICE_OWNER_ROUTER_INTF,
                network_id=subnet['network_id']).all()
            network_port = None
            for p in ports:
                if p['fixed_ips'][0]['subnet_id'] == subnet_id:
                    network_port = p
                    break
            assert network_port

            # Unlink the router and the bridge.
            mrouter = self.mido_mgmt.get_router(router_id)
            mbridge_port = self.mido_mgmt.get_port(network_port['id'])
            mrouter_port = self.mido_mgmt.get_port(mbridge_port.get_peer_id())
            mrouter_port.unlink()

            # Delete the route going to the bridge that has the subnet.
            found = False
            for r in mrouter.get_routes():
                if r.get_next_hop_port() == mrouter_port.get_id():
                    LOG.debug('Deleting route=%r ...', r)
                    r.delete()
                    found = True
                    #break   # commented out due to issue#314
            assert found

        super(MidonetPluginV2, self).remove_router_interface(context,
                router_id, interface_info)

    def update_floatingip(self, context, id, floatingip):
        LOG.debug('context=%r, id=%r, floatingip=%r', context, id, floatingip)

        session = context.session
        with session.begin(subtransactions=True):
            if floatingip['floatingip']['port_id']:
                fip = super(MidonetPluginV2, self).update_floatingip(
                        context, id, floatingip)
                router_id = fip['router_id']
                floating_address = fip['floating_ip_address']
                fixed_address = fip['fixed_ip_address']

                tenant_router = self.mido_mgmt.get_router(fip['router_id'])
                # find the provider router port that is connected to the tenant
                # of the floating ip
                for p in tenant_router.get_peer_ports():
                    if p.get_device_id() == self.provider_router.get_id():
                        pr_port = p

                # add a route for the floating ip to bring it to the tenant
                self.provider_router.add_route()\
                                    .type('Normal')\
                                    .src_network_addr('0.0.0.0')\
                                    .src_network_length(0)\
                                    .dst_network_addr(floating_address)\
                                    .dst_network_length(32)\
                                    .weight(100)\
                                    .next_hop_port(pr_port.get_id())\
                                    .create()

                chains = self.chain_manager.get_router_chains(fip['tenant_id'],
                                                              fip['router_id'])
                # add dnat/snat rule pair for the floating ip
                nat_targets = []
                nat_targets.append(
                    {'addressFrom': fixed_address, 'addressTo': fixed_address,
                     'portFrom': 0, 'portTo': 0})

                floating_property = {OS_FLOATING_IP_RULE_KEY: id}
                chains['in'].add_rule().nw_dst_address(floating_address)\
                                       .nw_dst_length(32)\
                                       .type('dnat')\
                                       .flow_action('accept')\
                                       .nat_targets(nat_targets)\
                                       .position(1)\
                                       .properties(floating_property)\
                                       .create()

                nat_targets = []
                nat_targets.append(
                    {'addressFrom': floating_address,
                     'addressTo': floating_address,
                     'portFrom': 0,
                     'portTo': 0})

                chains['out'].add_rule().nw_src_address(fixed_address)\
                                        .nw_src_length(32)\
                                        .type('snat')\
                                        .flow_action('accept')\
                                        .nat_targets(nat_targets)\
                                        .position(1)\
                                        .properties(floating_property)\
                                        .create()

            # disassociate floating IP
            elif floatingip['floatingip']['port_id'] is None:

                fip = super(MidonetPluginV2, self).get_floatingip(context, id)

                router_id = fip['router_id']
                floating_address = fip['floating_ip_address']
                fixed_address = fip['fixed_ip_address']

                # delete the route for this floating ip
                for r in self.provider_router.get_routes():
                    if r.get_dst_network_addr() == floating_address and \
                            r.get_dst_network_length() == 32:
                        r.delete()

                # delete snat/dnat rule pair for this floating ip
                chains = self.chain_manager.get_router_chains(fip['tenant_id'],
                                                              fip['router_id'])
                LOG.debug('chains=%r', chains)

                for r in chains['in'].get_rules():
                    if OS_FLOATING_IP_RULE_KEY in r.get_properties():
                        if r.get_properties()[OS_FLOATING_IP_RULE_KEY] == id:
                            LOG.debug('deleting rule=%r', r)
                            r.delete()
                            break

                for r in chains['out'].get_rules():
                    if OS_FLOATING_IP_RULE_KEY in r.get_properties():
                        if r.get_properties()[OS_FLOATING_IP_RULE_KEY] == id:
                            LOG.debug('deleting rule=%r', r)
                            r.delete()
                            break

                super(MidonetPluginV2, self).update_floatingip(context, id,
                                                               floatingip)

        return fip

    def _get_provider_owned_rouetrs(self):
        """Returns routers owned by provider"""

        if not self.provider_owned_routers:
            self.provider_owned_routers = self.mido_mgmt.get_routers(
                {'tenant_id': self.provider_tenant_id})
        return self.provider_owned_routers

    def _get_or_create_provider_router(self):
        """
        Get the provider router object, searching by name configured in the
        config file.
        If not found, it'll create one.
        """

        for r in self._get_provider_owned_rouetrs():
            if r.get_name() == self.provider_router_name:
                return r

        return self.mido_mgmt.add_router()\
                             .tenant_id(self.provider_tenant_id)\
                             .name(self.provider_router_name)\
                             .create()

    def _ensure_metadata_devices(self):
        """When quantum-server runs for the first time,
        it creates metadata router, bridge, link between them,
        and a exterior bridge port.

        If they are already set up, store the references to the
        instance variables.
        """

        #
        # MDR
        #
        found = False
        for r in self._get_provider_owned_rouetrs():
            if r.get_name() == self.metadata_router_name:
                self.metadata_router = r
                found = True

        if not found:
            # create MDR and an interior port.
            self.metadata_router = self.mido_mgmt.add_router()\
                                       .tenant_id(self.provider_tenant_id)\
                                       .name(self.metadata_router_name)\
                                       .create()

            mdr_port = self.metadata_router.add_interior_port()\
                                           .port_address('169.254.169.253')\
                                           .network_address('169.254.0.0')\
                                           .network_length(16)\
                                           .create()

            # Add a route to metadata server
            self.metadata_router.add_route().type('Normal')\
                                .src_network_addr('0.0.0.0')\
                                .src_network_length(0)\
                                .dst_network_addr('169.254.169.254')\
                                .dst_network_length(32)\
                                .weight(100)\
                                .next_hop_port(mdr_port.get_id())\
                                .create()

            # Create chains for metadata router
            chains = self.chain_manager.create_router_chains(
                    self.provider_tenant_id,
                    self.metadata_router.get_id())

            # set chains to in/out filters
            self.metadata_router.inbound_filter_id(chains['in'].get_id())\
                                .outbound_filter_id(chains['out'].get_id())\
                                .update()

            # add port translation rules for tcp port 80 <-> 8775
            nat_targets = []
            nat_targets.append(
                {'addressFrom': '169.254.169.254',
                 'addressTo': '169.254.169.254',
                 'portFrom': 8775,
                 'portTo': 8775
                 })

            chains['in'].add_rule().nw_dst_address('169.254.169.254')\
                                   .nw_dst_length(32)\
                                   .tp_dst_start(80)\
                                   .tp_dst_end(80)\
                                   .type('dnat')\
                                   .flow_action('accept')\
                                   .nat_targets(nat_targets)\
                                   .position(1)\
                                   .create()

            chains['out'].add_rule().nw_src_address('169.254.169.254')\
                                    .nw_src_length(32)\
                                    .tp_src_start(8775)\
                                    .tp_src_end(8775)\
                                    .type('rev_dnat')\
                                    .flow_action('accept')\
                                    .position(1)\
                                    .create()

        #
        # MDB
        #
        found = False
        for b in self.mido_mgmt.get_bridges(
            {'tenant_id': self.provider_tenant_id}):

            if b.get_name() == self.metadata_bridge_name:
                self.metadata_bridge = b
                found = True

        if not found:
            # create MDB and an interior port on it, then link it to MDR
            self.metadata_bridge = self.mido_mgmt.add_bridge()\
                                       .tenant_id(self.provider_tenant_id)\
                                       .name(self.metadata_bridge_name)\
                                       .create()

            mdb_port = self.metadata_bridge.add_interior_port().create()
            mdb_port.link(mdr_port.get_id())

            # create a exterior port on MDB
            self.metadata_bridge.add_exterior_port().create()
