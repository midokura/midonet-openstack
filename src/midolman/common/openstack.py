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

from nova import context
from nova import db
from nova.openstack.common import log as logging

import midonet.client.port_type as PortType


LOG = logging.getLogger('nova...' + __name__)

PREFIX = 'os_sg_'
SUFFIX_IN = '_in'
SUFFIX_OUT = '_out'
OS_ROUTER_IN_CHAIN_NAME_FORMAT = 'OS_IN_%s'
OS_ROUTER_OUT_CHAIN_NAME_FORMAT = 'OS_OUT_%s'


def sg_label(sg_id, sg_name):
    if sg_name == 'default':
        label = PREFIX + 'default'
    else:
        label = PREFIX + str(sg_id) + '_' + sg_name
    return label

chain_name = sg_label
port_group_name = sg_label


class ChainManager:

    TENANT_ROUTER_IN = 'os_project_router_in'
    TENANT_ROUTER_OUT = 'os_project_router_out'

    def __init__(self, midonet_client):
        self.mido_conn = midonet_client

    def _chain_name_for_vif(self, vif_uuid, direction):
        global PREFIX
        return PREFIX + 'vif_' + vif_uuid + '_' + direction

    def create_for_sg(self, tenant_id, sg_id, sg_name):
        LOG.debug('tenant_id=%r, sg_id=%r, sg_name=%r', tenant_id, sg_id,
                  sg_name)

        cname = chain_name(sg_id, sg_name)
        self.mido_conn.add_chain().tenant_id(tenant_id).name(cname).create()

    def delete_for_sg(self, tenant_id, sg_id):
        LOG.debug('tenant_id=%r, sg_id=%r', tenant_id, sg_id)

        chain_name_prefix = chain_name(sg_id, '')
        chains = self.mido_conn.get_chains({'tenant_id': tenant_id})
        for c in chains:
            if c.get_name().startswith(chain_name_prefix):
                LOG.debug('deleting chain=%r', c)
                c.delete()

    def create_for_vif(self, tenant_id, vif_id):
        """Create chains for the vif and returns a dictionary that
           contains chain resources for in and out with keys 'in' and 'out'
        """
        LOG.debug('tenant_id=%r, vif_id=%r', tenant_id, vif_id)

        # see if there are already there
        chains = self.mido_conn.get_chains({'tenant_id': tenant_id})
        for c in chains:
            if c.get_name().startswith(self._chain_name_for_vif(vif_id, '')):
                assert False, 'chain for vif should not be there'

        # create a inbound chain
        in_chain = self.mido_conn.add_chain()\
                                 .tenant_id(tenant_id)\
                                 .name(self._chain_name_for_vif(vif_id, 'in'))\
                                 .create()

        # create a outbound chain
        out_chain = self.mido_conn\
                .add_chain()\
                .tenant_id(tenant_id)\
                .name(self._chain_name_for_vif(vif_id, 'out'))\
                .create()

        return {'in': in_chain, 'out': out_chain}

    def delete_for_vif(self, tenant_id, vif_id):
        """Deletes the in and out chains for the VIF. Rules under the chains
           are cascade deleted.
        """
        LOG.debug('tenant_id=%r, vif_id=%r', tenant_id, vif_id)
        chains = self.mido_conn.get_chains({'tenant_id': tenant_id})
        for c in chains:
            if c.get_name().startswith(self._chain_name_for_vif(vif_id, '')):
                c.delete()

    def get_router_chains(self, tenant_id, router_id):
        """
        Returns a dictionary that has in/out chain resources key'ed with 'in'
        and 'out' respectively, given the tenant_id and the router_id passed
        in in the arguments.
        """

        router_chain_names = self._get_router_chain_names(router_id)
        chains = {}
        for c in  self.mido_conn.get_chains({'tenant_id': tenant_id}):
            if c.get_name() == router_chain_names['in']:
                chains['in'] = c
            elif c.get_name() == router_chain_names['out']:
                chains['out'] = c
        return chains

    def create_router_chains(self, tenant_id, router_id):
        """
        Creates chains for the router and returns the same dictionary as
        get_router_chains() returns.
        """
        chains = {}
        router_chain_names = self._get_router_chain_names(router_id)
        chains['in'] = self.mido_conn.add_chain()\
                           .tenant_id(tenant_id)\
                           .name(router_chain_names['in'])\
                           .create()

        chains['out'] = self.mido_conn.add_chain()\
                            .tenant_id(tenant_id)\
                            .name(router_chain_names['out'])\
                            .create()
        return chains

    def _get_router_chain_names(self, router_id):

        in_name = OS_ROUTER_IN_CHAIN_NAME_FORMAT % router_id
        out_name = OS_ROUTER_OUT_CHAIN_NAME_FORMAT % router_id
        router_chain_names = {'in': in_name, 'out': out_name}
        return router_chain_names


class PortGroupManager:

    def __init__(self, midonet_client):
        self.mido_conn = midonet_client

    def create(self, tenant_id, sg_id, sg_name):
        LOG.debug('tenant_id=%r, sg_id=%r, sg_name=%r', tenant_id, sg_id,
                  sg_name)
        pg_name = port_group_name(sg_id, sg_name)
        self.mido_conn.add_port_group().tenant_id(tenant_id).name(
            pg_name).create()

    def delete(self, tenant_id, sg_id, sg_name):
        LOG.debug('tenant_id=%r, sg_id=%r, sg_name=%r', tenant_id, sg_id,
                  sg_name)
        pg_name_prefix = port_group_name(sg_id, sg_name)
        pgs = self.mido_conn.get_port_groups({'tenant_id': tenant_id})
        for pg in pgs:
            if pg.get_name().startswith(pg_name_prefix):
                LOG.debug('deleting port group=%r', pg)
                pg.delete()


class RuleManager:

    OS_SG_KEY = 'os_sg_rule_id'

    def __init__(self, midonet_client):
        self.mido_conn = midonet_client

    def _properties(self, os_sg_rule_id):
        return {self.OS_SG_KEY: str(os_sg_rule_id)}

    def create_for_sg(self, tenant_id, sg_id, sg_name, rule):
        LOG.debug('sg_ig=%r, sg_name=%r', sg_id, sg_name)
        LOG.debug('parent_group_id=%r', rule['parent_group_id'])
        LOG.debug('protocol=%r', rule['protocol'])
        LOG.debug('from_port=%r', rule['from_port'])
        LOG.debug('to_port=%r', rule['to_port'])
        LOG.debug('cidr=%r', rule['cidr'])

        cname = chain_name(sg_id, sg_name)

        # search for the chain to put rules
        chains = self.mido_conn.get_chains({'tenant_id': tenant_id})
        found = False
        for c in chains:
            if c.get_name() == cname:
                sg_chain = c
                found = True
        assert found
        LOG.debug('putting a rule to the chain id=%r', sg_chain.get_id())

        # construct a corresponding rule
        tp_src_start = tp_src_end = None
        tp_dst_start = tp_dst_end = None
        nw_src_address = None
        nw_src_length = None
        port_group_id = None

        # handle source
        if rule['cidr'] != None:
            nw_src_address, nw_src_length = rule['cidr'].split('/')
        else:  # security group as a srouce
            port_groups = self.mido_conn.get_port_groups(
                {'tenant_id': tenant_id})
            ctxt = context.get_admin_context()
            group = db.security_group_get(ctxt, rule['group_id'])

            pg_name = port_group_name(group['id'], group['name'])
            found = False
            for pg in port_groups:
                if pg.get_name() == pg_name:
                    port_group_id = pg.get_id()
                    found = True
            assert found

        # dst ports
        tp_dst_start, tp_dst_end = rule['from_port'], rule['to_port']

        # protocol
        if rule['protocol'] == 'tcp':
            nw_proto = 6
        elif rule['protocol'] == 'udp':
            nw_proto = 17
        elif rule['protocol'] == 'icmp':
            nw_proto = 1
            # extract type and code from reporposed fields
            icmp_type = rule['from_port']
            icmp_code = rule['to_port']

            # translate -1(wildcard in OS) to midonet wildcard
            if icmp_type == -1:
                icmp_type = None
            if icmp_code == -1:
                icmp_code = None

            # set data for midonet rule
            tp_src_start = tp_src_end = icmp_type
            tp_dst_start = tp_dst_end = icmp_code

        # create an accept rule
        properties = self._properties(rule['id'])
        chain = self.mido_conn.get_chain(sg_chain.get_id())
        chain.add_rule().port_group(port_group_id)\
                        .type('accept')\
                        .nw_proto(nw_proto)\
                        .nw_src_address(nw_src_address)\
                        .nw_src_length(nw_src_length)\
                        .tp_src_start(tp_src_start)\
                        .tp_src_end(tp_src_end)\
                        .tp_dst_start(tp_dst_start)\
                        .tp_dst_end(tp_dst_end)\
                        .properties(properties)\
                        .create()

    def delete_for_sg(self, tenant_id, rule_id):
        LOG.debug('tenant_id=%r, rule_id=%r', tenant_id, rule_id)

        properties = self._properties(rule_id)
        # search for the chains to find the rule to delete
        chains = self.mido_conn.get_chains({'tenant_id': tenant_id})
        for c in chains:
            rules = c.get_rules()
            for r in rules:
                if r.get_properties() == properties:
                    LOG.debug('deleting rule=%r', r)
                    r.delete()

    def create_for_vif(self, tenant_id, instance, network, vif_chains,
            allow_same_net_traffic):
        LOG.debug('tenant_id=%r, instance=%r, network=%r, vif_chains=%r',
                  tenant_id, instance['id'], network, vif_chains)

        bridge_uuid = network[0]['id']
        net_cidr = network[0]['cidr']
        vif_uuid = network[1]['vif_uuid']
        mac = network[1]['mac']
        ip = network[1]['ips'][0]['ip']

        #
        # ingress
        #

        position = 1
        in_chain = vif_chains['in']
        out_chain = vif_chains['out']
        # mac spoofing protection
        in_chain.add_rule().type('drop')\
                           .dl_src(mac)\
                           .inv_dl_src(True)\
                           .position(position)\
                           .create()
        position += 1

        # ip spoofing protection
        in_chain.add_rule().type('drop')\
                           .nw_src_address(ip)\
                           .nw_src_length(32)\
                           .inv_nw_src(True)\
                           .dl_type(0x0800)\
                           .position(position)\
                           .create()
        position += 1

        # conntrack
        in_chain.add_rule().type('accept')\
                           .match_forward_flow(True)\
                           .position(position)\
                           .create()
        position += 1

        #
        # egress
        #
        ctxt = context.get_admin_context()
        security_groups = db.security_group_get_by_instance(ctxt,
                instance['id'])

        position = 1
        # get the port groups to match for the rule
        port_groups = self.mido_conn.get_port_groups({'tenant_id': tenant_id})

        if allow_same_net_traffic:
            LOG.debug('accept cidr=%r', net_cidr)
            nw_src_address, nw_src_length = net_cidr.split('/')
            out_chain.add_rule().type('accept')\
                                .nw_src_address(nw_src_address)\
                                .nw_src_length(nw_src_length)\
                                .position(position)\
                                .create()
            position += 1

        # add rules that correspond to Nova SG
        for sg in security_groups:
            LOG.debug('security group=%r', sg['name'])
            rules = db.security_group_rule_get_by_security_group(ctxt,
                                                    sg['id'])
            LOG.debug('sg_id=%r', sg['id'])
            LOG.debug('sg_project_id=%r', sg['project_id'])
            LOG.debug('name=%r', sg['name'])
            LOG.debug('rules=%r', rules)

            cname = chain_name(sg['id'], sg['name'])
            chains = self.mido_conn.get_chains({'tenant_id': tenant_id})
            jump_chain_id = None
            for c in chains:
                if c.get_name() == cname:
                    jump_chain_id = c.get_id()
                    break
            assert jump_chain_id != None

            rule = out_chain.add_rule().type('jump')\
                                       .position(position)\
                                       .jump_chain_id(jump_chain_id)\
                                       .jump_chain_name(cname)\
                                       .create()
            position += 1

            # Look for the port group that the vif should belong to
            for pg in port_groups:
                if pg.get_name() != cname:
                    port_groups.remove(pg)

        # add reverse flow matching at the end
        out_chain.add_rule().type('accept')\
                            .match_return_flow(True)\
                            .position(position)\
                            .create()
        position += 1

        # fall back DROP rule at the end except for ARP
        out_chain.add_rule().type('drop')\
                            .dl_type(0x0806)\
                            .inv_dl_type(True)\
                            .position(position)\
                            .create()

        #
        # Updating the vport
        #
        bridge = self.mido_conn.get_bridge(bridge_uuid)
        bridge_port = self.mido_conn.get_port(vif_uuid)
        LOG.debug('bridge_port=%r found', bridge_port)

        # set filters
        bridge_port.inbound_filter_id(in_chain.get_id())
        bridge_port.outbound_filter_id(out_chain.get_id())
        bridge_port.update()
        for pg in port_groups:
            pg.add_port_group_port().port_id(bridge_port.get_id()).create()
