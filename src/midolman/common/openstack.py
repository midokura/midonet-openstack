# vim: tabstop=4 shiftwidth=4 softtabstop=4
# Copyright (C) 2011 Midokura Japan KK
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
from nova import log as logging

from midonet.api import PortType

LOG = logging.getLogger('nova...' + __name__)

PREFIX = 'os_sg_'
SUFFIX_IN = '_in'
SUFFIX_OUT = '_out'


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
        response, content = self.mido_conn.chains().create(tenant_id, cname)

    def delete_for_sg(self, tenant_id, sg_id):
        LOG.debug('tenant_id=%r, sg_id=%r', tenant_id, sg_id)

        chain_name_prefix = chain_name(sg_id, '')
        response, chains = self.mido_conn.chains().list(tenant_id)
        for c in chains:
            if c['name'].startswith(chain_name_prefix):
                LOG.debug('deleting chain=%r', c)
                response, content = self.mido_conn.delete(c['uri'])

    def create_for_vif(self, tenant_id, vif_id):
        """Create chains for the vif and returns a dictionary that
           contains chain resources for in and out with keys 'in' and 'out'
        """
        LOG.debug('tenant_id=%r, vif_id=%r', tenant_id, vif_id)

        # see if there are already there
        res, chains = self.mido_conn.chains().list(tenant_id)
        for c in chains:
            if c['name'].startswith(self._chain_name_for_vif(vif_id, '')):
                assert False, 'chain for vif should not be there'

        # create a inbound chain
        response, content = self.mido_conn.chains().create(tenant_id,
                self._chain_name_for_vif(vif_id, 'in'))
        response, in_chain = self.mido_conn.get(response['location'])

        # create a outbound chain
        response, content = self.mido_conn.chains().create(tenant_id,
                self._chain_name_for_vif(vif_id, 'out'))
        response, out_chain = self.mido_conn.get(response['location'])

        return {'in': in_chain, 'out': out_chain}

    def delete_for_vif(self, tenant_id, vif_id):
        """Deletes the in and out chains for the VIF. Rules under the chains
           are cascade deleted.
        """
        LOG.debug('tenant_id=%r, vif_id=%r', tenant_id, vif_id)
        response, chains = self.mido_conn.chains().list(tenant_id)
        for c in chains:
            if c['name'].startswith(self._chain_name_for_vif(vif_id, '')):
                response, content = self.mido_conn.delete(c['uri'])

class PortGroupManager:

    def __init__(self, midonet_client):
        self.mido_conn = midonet_client

    def create(self, tenant_id, sg_id, sg_name):
        LOG.debug('tenant_id=%r, sg_id=%r, sg_name=%r', tenant_id, sg_id,
                  sg_name)
        pg_name = port_group_name(sg_id, sg_name)
        response, content = self.mido_conn.port_groups().create(tenant_id,
                                                pg_name)

    def delete(self, tenant_id, sg_id, sg_name):
        LOG.debug('tenant_id=%r, sg_id=%r, sg_name=%r', tenant_id, sg_id,
                  sg_name)
        pg_name_prefix = port_group_name(sg_id, sg_name)
        response, pgs = self.mido_conn.port_groups().list(tenant_id)
        for pg in pgs:
            if pg['name'].startswith(pg_name_prefix):
                LOG.debug('deleting port group=%r', pg)
                response, content = self.mido_conn.delete(pg['uri'])

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
        response, chains = self.mido_conn.chains().list(tenant_id)
        found = False
        for c in chains:
            if c['name'] == cname:
                sg_chain = c
                found = True
        assert found
        LOG.debug('putting a rule to the chain id=%r', sg_chain['id'])

        # construct a corresponding rule
        tp_src_start = tp_src_end = None
        tp_dst_start = tp_dst_end = None
        nw_src_address = None
        nw_src_length = None
        port_group_id = None

        # handle source
        if rule['cidr'] != None:
            nw_src_address, nw_src_length  = rule['cidr'].split('/')
        else: # security group as a srouce
            response, port_groups = self.mido_conn.port_groups().list(
                    tenant_id)
            ctxt = context.get_admin_context()
            group = db.security_group_get(ctxt, rule['group_id'])

            pg_name = port_group_name(group['id'], group['name'])
            found = False
            for pg in port_groups:
                if pg['name'] == pg_name:
                    port_group_id = pg['id']
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
        response, content = self.mido_conn.rules().create(tenant_id,
                sg_chain['id'], port_group=port_group_id,
                type_='accept', nw_proto=nw_proto,
                nw_src_address=nw_src_address, nw_src_length=nw_src_length,
                tp_src_start=tp_src_start, tp_src_end=tp_src_end,
                tp_dst_start=tp_dst_start, tp_dst_end=tp_dst_end,
                properties=properties)


    def delete_for_sg(self, tenant_id, rule_id):
        LOG.debug('tenant_id=%r, rule_id=%r', tenant_id, rule_id)

        properties = self._properties(rule_id)
        # search for the chains to find the rule to delete
        response, chains = self.mido_conn.chains().list(tenant_id)
        for c in chains:
            response, rules = self.mido_conn.get(c['rules'])
            for r in rules:
                if r['properties'] == properties:
                    LOG.debug('deleting rule=%r', r)
                    response, content = self.mido_conn.delete(r['uri'])

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
        # arp spoofing protection
        response, content = self.mido_conn.rules().create(tenant_id,
                vif_chains['in']['id'], type_='drop',
                dl_src=mac, inv_dl_src=True, position=position)
        position += 1

        # ip spoofing protection
        response, content = self.mido_conn.rules().create(tenant_id,
                vif_chains['in']['id'], type_='drop',
                nw_src_address=ip, nw_src_length=32, inv_nw_src=True,
                dl_type=0x0800, position=position)
        position += 1

        # conntrack
        response, content = self.mido_conn.rules().create(tenant_id,
                vif_chains['in']['id'], type_='accept',
                match_forward_flow=True, position=position)
        position += 1

        #
        # egress
        #
        ctxt = context.get_admin_context()
        security_groups = db.security_group_get_by_instance(ctxt,
                instance['id'])

        position = 1
        # get the port groups to match for the rule
        port_group_ids = []
        response, port_groups = self.mido_conn.port_groups().list(tenant_id)

        if allow_same_net_traffic:
            LOG.debug('accept cidr=%r', net_cidr)
            nw_src_address, nw_src_length  = net_cidr.split('/')
            response, content = self.mido_conn.rules().create(tenant_id,
                    vif_chains['out']['id'], type_='accept',
                    nw_src_address=nw_src_address, nw_src_length=nw_src_length,
                    position=position)
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
            response, content = self.mido_conn.rules().create(tenant_id,
                    vif_chains['out']['id'], type_='jump',
                    jump_chain_name=cname, position=position)
            position += 1

            # Look for the port group that the vif should belong to
            for pg in port_groups:
                if pg['name'] == cname:
                    port_group_ids.append(pg['id'])

        # add reverse flow matching at the end
        response, content = self.mido_conn.rules().create(tenant_id,
                vif_chains['out']['id'], type_='accept', match_return_flow=True,
                position=position)
        position += 1

        # fall back DROP rule at the end except for ARP
        response, content = self.mido_conn.rules().create(tenant_id,
                vif_chains['out']['id'], type_='drop', dl_type=0x0806,
                inv_dl_type=True, position=position)

        #
        # Updating the vport
        #
        response, bridge_ports = self.mido_conn.bridge_ports().list(tenant_id,
                bridge_uuid)

        # Search for the port that has the vif attached
        found = False
        for bp in bridge_ports:
            if bp['type'] != PortType.MATERIALIZED_BRIDGE:
                continue
            if bp['vifId'] == vif_uuid:
                bridge_port = bp
                found = True
                break
        assert found
        LOG.debug('bridge_port=%r found', bridge_port)

        # set filters and port group ids
        bridge_port['inboundFilterId'] = vif_chains['in']['id']
        bridge_port['outboundFilterId'] = vif_chains['out']['id']
        bridge_port['portGroupIDs'] = port_group_ids
        response, content = self.mido_conn.bridge_ports().update(tenant_id,
                bridge_uuid, bridge_port['id'], bridge_port)


class RouterName:
    PROVIDER_ROUTER = 'provider_router'
    TENANT_ROUTER = 'os_project_router'


