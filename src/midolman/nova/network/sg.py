# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2012 Midokura Japan, K.K.
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
from nova import flags
from nova.network.quantum.sg import SecurityGroupHandlerBase
from nova.virt.firewall import FirewallDriver
from nova import log as logging

from nova.network.quantum.manager import QuantumManager
from midolman.nova.network import midonet_connection
from midolman.common.openstack import ChainName, RouterName, Rule
from midonet.api import PortType


LOG = logging.getLogger('nova...' + __name__)
FLAGS = flags.FLAGS

class MidonetFirewallDriver(FirewallDriver):
    """Firewall driver to setup security group in MidoNet.
       This is called from nova-compute. Since we don't really
       depend on the virt driver, this file is in midolman.nova.network.
    """

    def __init__(self, **kwargs):
        LOG.debug('kwargs=%r', kwargs)
        self.mido_conn = midonet_connection.get_connection()

    def prepare_instance_filter(self, instance, network_info):
        LOG.debug('instance=%r, network_info=%r', instance, network_info)

        ctxt = context.get_admin_context()
        #Allow project network traffic
        if FLAGS.allow_same_net_traffic:
            #TODO: add appropriate rules?
            pass

        # create chains for this vif
        vif_uuid = network_info[0][1]['vif_uuid']
        chains_for_vif = ChainName.chain_names_for_vif(vif_uuid)

        tenant_id = instance['project_id']
        response, chains = self.mido_conn.chains().list(tenant_id)
        for c in chains:
            if c['name'] == chains_for_vif['in']:
                LOG.debug('Returning; chains already there.')
                return

        response, content = self.mido_conn.chains().create(tenant_id,
                chains_for_vif['in'])
        response, in_chain = self.mido_conn.get(response['location'])

        response, content = self.mido_conn.chains().create(tenant_id,
                chains_for_vif['out'])
        response, out_chain = self.mido_conn.get(response['location'])


        # ingress for conntrack
        response, content = self.mido_conn.rules().create(tenant_id,
                in_chain['id'], type_='accept',
                match_forward_flow=True)

        in_pos = 1
        security_groups = db.security_group_get_by_instance(ctxt,
                instance['id'])
        LOG.debug('security_groups=%r', security_groups)

        port_group_ids = []
        # get the port groups to match for the rule
        response, port_groups = self.mido_conn.port_groups().list(tenant_id)

        #
        # egress to handle security group rules
        #
        for security_group in security_groups:
            rules = db.security_group_rule_get_by_security_group(ctxt,
                    security_group['id'])
            LOG.debug('==================================')
            LOG.debug('sg_id=%r', security_group['id'])
            LOG.debug('sg_project_id=%r', security_group['project_id'])
            LOG.debug('name=%r', security_group['name'])
            LOG.debug('rules=%r', rules)
            LOG.debug('chain_name=%r', ChainName.sg_chain_name(
                      security_group['id'], security_group['name']))

            label=ChainName.sg_chain_name(
                    security_group['id'],
                    security_group['name'])
            if security_group['name'] == 'default':
                label = ChainName.SG_DEFAULT

            response, content = self.mido_conn.rules().create(tenant_id,
                    out_chain['id'], type_='jump',
                    jump_chain_name=label)
            in_pos += 1

            for pg in port_groups:
                if pg['name'] == label:
                    port_group_ids.append(pg['id'])

        # add reverse flow matching at the end
        response, content = self.mido_conn.rules().create(tenant_id,
                out_chain['id'], type_='accept', match_return_flow=True,
                position=in_pos)
        in_pos += 1

        # fallback REJECT rule at the end except for the ARP
        # TODO: should limit the arp from tenant router and the same portgroups
        # TODO: Reasearch on default behaviour(when no rules inside SG), and
        #       and handle REJECT accordingly.
        response, content = self.mido_conn.rules().create(tenant_id,
                out_chain['id'], type_='drop', dl_type=0x0806,
                inv_dl_type=True, position=in_pos)

        #
        # Now set the filters and port group ids to the port
        #
        bridge_uuid = network_info[0][0]['id']
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

        bridge_port['inboundFilterId'] = in_chain['id']
        bridge_port['outboundFilterId'] = out_chain['id']
        bridge_port['portGroupIDs'] = port_group_ids
        response, content = self.mido_conn.bridge_ports().update(tenant_id,
                bridge_uuid, bridge_port['id'], bridge_port)

    def unfilter_instance(self, instance, network_info):
        LOG.debug('instance=%r, network_info=%r', instance, network_info)

        if network_info == []:
            LOG.debug('Cannot unfilter the instance=%r; no vif info available',
                      instance['id'])
            return

        ctxt = context.get_admin_context()
        tenant_id = instance['project_id']

        # delete chains for the vif
        vif_uuid = network_info[0][1]['vif_uuid']

        chains_for_vif = ChainName.chain_names_for_vif(vif_uuid)
        response, chains = self.mido_conn.chains().list(tenant_id)
        for c in chains:
            if c['name'] == chains_for_vif['in'] or \
                    c['name'] == chains_for_vif['out']:
                response, content = self.mido_conn.chains().delete(tenant_id,
                        c['id'])

    def apply_instance_filter(self, instance, network_info):
        LOG.debug('instance=%r, network_info=%r', instance, network_info)
        pass

    def refresh_security_group_rules(self, security_group_id):
        LOG.debug('security_group_id=%r', security_group_id)

    def refresh_security_group_members(self, security_group_id):
        LOG.debug('security_group_id=%r', security_group_id)

    def refresh_provider_fw_rules(self):
        LOG.debug('')

    def setup_basic_filtering(self, instance, network_info):
        LOG.debug('instance=%r, network_info=%r', instance, network_info)

    def instance_filter_exists(self, instance, network_info):
        LOG.debug('instance=%r, network_info=%r', instance, network_info)
        #TODO?: Implement this?

class MidonetSecurityGroupHandler(SecurityGroupHandlerBase):
    """ This is security groups handler for MidoNet.
        When security groups and rules are modified, this handler gets
        called from nova-api.
    """

    def __init__(self):
        LOG.debug('')
        self.mido_conn = midonet_connection.get_connection()

    def trigger_security_group_create_refresh(self, context, group):

        LOG.debug('group=%r', group)
        ctxt = context.elevated()
        sg_ref = db.security_group_get_by_name(ctxt, group['project_id'],
                                               group['name'] )

        # create a chain for the security group
        chain_name = ChainName.sg_chain_name(sg_ref['id'], group['name'])
        tenant_id = group['project_id']
        response, content = self.mido_conn.chains().create(tenant_id,
                chain_name)

        # create a port group for the security group
        port_group_name = chain_name
        response, content = self.mido_conn.port_groups().create(tenant_id,
                                                port_group_name)

    def trigger_security_group_destroy_refresh(self, context,
                                               security_group_id):
        LOG.debug('security_group_id=%r', security_group_id)
        tenant_id = context.to_dict()['project_id']
        response, chains = self.mido_conn.chains().list(tenant_id)
        for c in chains:
            LOG.debug('chain=%r', c)
            if c['name'].startswith(ChainName.sg_chain_name_prefix(
                        security_group_id)):
                response, content = self.mido_conn.chains().delete(tenant_id,
                        c['id'])

    def trigger_security_group_rule_create_refresh(self, context, rule_ids):
        LOG.debug('rule_ids=%r', rule_ids)
        ctxt = context.elevated()
        tenant_id = context.to_dict()['project_id']

        for rule_id in rule_ids:
            rule = db.security_group_rule_get(ctxt, rule_id)
            LOG.debug('rule=%r', rule)
            LOG.debug('sg_id=%r', rule['parent_group_id'])
            LOG.debug('protocol=%r', rule['protocol'])
            LOG.debug('from_port=%r', rule['from_port'])
            LOG.debug('to_port=%r', rule['to_port'])
            LOG.debug('cidr=%r', rule['cidr'])

            group = db.security_group_get(ctxt, rule['parent_group_id'])
            is_default_group = group['name'] == 'default'

            # search for chains to put rules
            response, chains = self.mido_conn.chains().list(tenant_id)
            for c in chains:
                if ChainName.is_chain_name_for_rule(c['name'],
                        rule['parent_group_id'], is_default_group):
                    sg_chain = c

            # construct a corresponding rule
            tp_src_start = None # for ICMP type
            nw_src_address = None
            nw_src_length = None
            port_group = None

            # src handling
            if rule['cidr'] != None:
                nw_src_address, nw_src_length  = rule['cidr'].split('/')
            else:
                group = db.security_group_get(ctxt, rule['group_id'])
                sg_name = group['name']
                response, port_groups = self.mido_conn.port_groups().list(
                        tenant_id)

                if group['name'] == 'default':
                    pg_name = ChainName.SG_DEFAULT
                else:
                    pg_name = ChainName.sg_chain_name(group['id'],
                                                      group['name'])
                found = False
                for pg in port_groups:
                    if pg['name'] == pg_name:
                        port_group = pg['id']
                        found = True
                assert found

            tp_dst_start, tp_dst_end = rule['from_port'], rule['to_port']

            if rule['protocol'] == 'tcp':
                nw_proto = 6
            elif rule['protocol'] == 'udp':
                nw_proto = 17
            elif rule['protocol'] == 'icmp':
                nw_proto = 1
                # OpenStack repurpose
                icmp_type = rule['from_port']
                icmp_code = rule['to_port']

                tp_dst_start = None
                tp_dst_end = None

                # MidoNet repurposes like these:
                tp_src_start = icmp_type
                tp_dst_start = icmp_code

            # create an accept rule
            properties = Rule.properties(rule_id)
            response, content = self.mido_conn.rules().create(tenant_id,
                    sg_chain['id'], port_group=port_group,
                    type_='accept', nw_proto=nw_proto,
                    nw_src_address=nw_src_address, nw_src_length=nw_src_length,
                    tp_dst_start=tp_dst_start, tp_dst_end=tp_dst_end,
                    tp_src_start=tp_src_start, properties=properties)

    def trigger_security_group_rule_destroy_refresh(self, context,
                                                     rule_ids):
        LOG.debug('rule_ids=%r', rule_ids)
        ctxt = context.elevated()
        tenant_id = context.to_dict()['project_id']

        # Note: this is not efficient, may as well cache it
        for rule_id in rule_ids:
            properties = Rule.properties(rule_id)
            # search for chains to put rules
            response, chains = self.mido_conn.chains().list(tenant_id)
            for c in chains:
                response, rules = self.mido_conn.get(c['rules'])
                for r in rules:
                    if r['properties'] == properties:
                        LOG.debug('deleting rule=%r', r)
                        response, content = self.mido_conn.delete(r['uri'])

    def trigger_instance_add_security_group_refresh(self, context, instance,
                                                    group_name):
        LOG.debug('instance=%r, group_name=%r', instance, group_name)

    def trigger_instance_remove_security_group_refresh(self, context, instance,
                                                       group_name):
        LOG.debug('instance=%r, group_name=%r', instance, group_name)

    def trigger_security_group_members_refresh(self, context, group_ids):
        LOG.debug('group_ids=%r', group_ids)
