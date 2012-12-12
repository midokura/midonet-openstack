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
from nova import flags
from nova.network.quantum.sg import SecurityGroupHandlerBase
from nova.virt.firewall import FirewallDriver
from nova import log as logging

from nova.network.quantum.manager import QuantumManager
from midolman.nova.network import midonet_connection
from midolman.common.openstack import ChainManager, PortGroupManager,\
        RuleManager
import midonet.client.port_type as PortType


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
        self.chain_manager = ChainManager(self.mido_conn)
        self.rule_manager = RuleManager(self.mido_conn)

    def prepare_instance_filter(self, instance, network_info):
        LOG.debug('instance=%r, network_info=%r', instance, network_info)

        if network_info == []:
            LOG.info('Do nothing as there is no networks')
            return

        ctxt = context.get_admin_context()

        # create chains for this vif
        tenant_id = instance['project_id']

        for network in network_info:
            vif_uuid = network[1]['vif_uuid']

            # create chains for this vif
            try:
                vif_chains = self.chain_manager.create_for_vif(tenant_id,
                        vif_uuid)
            except AssertionError as e:
                LOG.info('Returning; chains already there: instance=%r',
                         instance['id'])
                return

            self.rule_manager.create_for_vif(tenant_id, instance, network,
                    vif_chains, FLAGS.allow_same_net_traffic)

    def unfilter_instance(self, instance, network_info):
        LOG.debug('instance=%r, network_info=%r', instance, network_info)

        if network_info == []:
            LOG.debug('Cannot unfilter the instance=%r; no vif info available',
                      instance['id'])
            return

        ctxt = context.get_admin_context()
        tenant_id = instance['project_id']

        for network in network_info:
            vif_uuid = network[1]['vif_uuid']
            vif_chains = self.chain_manager.delete_for_vif(tenant_id, vif_uuid)

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
        return True

class MidonetSecurityGroupHandler(SecurityGroupHandlerBase):
    """ This is security groups handler for MidoNet.
        When security groups and rules are modified, this handler gets
        called from nova-api.
    """

    def __init__(self):
        LOG.debug('')
        self.mido_conn = midonet_connection.get_connection()
        self.chain_manager = ChainManager(self.mido_conn)
        self.pg_manager = PortGroupManager(self.mido_conn)
        self.rule_manager = RuleManager(self.mido_conn)

    def trigger_security_group_create_refresh(self, context, group):
        """Create a chain and port group for the security group."""

        LOG.debug('group=%r', group)
        ctxt = context.elevated()
        sg_ref = db.security_group_get_by_name(ctxt, group['project_id'],
                                               group['name'] )

        tenant_id = context.to_dict()['project_id']
        sg_id = sg_ref['id']
        sg_name = group['name']

        # create a chain for the security group
        self.chain_manager.create_for_sg(tenant_id, sg_id, sg_name)

        # create a port group for the security group
        self.pg_manager.create(tenant_id, sg_id, sg_name)

    def trigger_security_group_destroy_refresh(self, context,
                                               security_group_id):
        LOG.debug('security_group_id=%r', security_group_id)

        tenant_id = context.to_dict()['project_id']
        # delete corresponding chain
        self.chain_manager.delete_for_sg(tenant_id, security_group_id)

        # delete the port group
        self.pg_manager.delete(tenant_id, security_group_id, '')

    def trigger_security_group_rule_create_refresh(self, context, rule_ids):
        LOG.debug('rule_ids=%r', rule_ids)
        ctxt = context.elevated()
        tenant_id = context.to_dict()['project_id']

        for rule_id in rule_ids:
            rule = db.security_group_rule_get(ctxt, rule_id)

            group = db.security_group_get(ctxt, rule['parent_group_id'])
            sg_id = rule['parent_group_id']
            sg_name = group['name']

            self.rule_manager.create_for_sg(tenant_id, sg_id, sg_name, rule)

    def trigger_security_group_rule_destroy_refresh(self, context, rule_ids):
        LOG.debug('rule_ids=%r', rule_ids)
        ctxt = context.elevated()
        tenant_id = context.to_dict()['project_id']

        for rule_id in rule_ids:
            self.rule_manager.delete_for_sg(tenant_id, rule_id)

    def trigger_instance_add_security_group_refresh(self, context, instance,
                                                    group_name):
        LOG.debug('instance=%r, group_name=%r', instance, group_name)

    def trigger_instance_remove_security_group_refresh(self, context, instance,
                                                       group_name):
        LOG.debug('instance=%r, group_name=%r', instance, group_name)

    def trigger_security_group_members_refresh(self, context, group_ids):
        LOG.debug('group_ids=%r', group_ids)
