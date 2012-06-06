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

class ChainName:
    TENANT_ROUTER_IN = 'os_project_router_in'
    TENANT_ROUTER_OUT = 'os_project_router_out'

    PREFIX = 'os_sg_'
    SUFFIX_IN = '_in'
    SUFFIX_OUT = '_out'

    SG_DEFAULT = PREFIX + 'default'

    @classmethod
    def sg_chain_name_prefix(cls, sg_id):
        return cls.PREFIX + str(sg_id) + '_'

    @classmethod
    def sg_chain_name(cls, sg_id, sg_name):
        prefix = cls.sg_chain_name_prefix(sg_id)
        return prefix + sg_name

    @classmethod
    def vif_chain_prefix(cls):
        return cls.PREFIX + 'vif_'

    @classmethod
    def chain_names_for_vif(cls, vif_uuid):
        in_ = cls.vif_chain_prefix() + vif_uuid + cls.SUFFIX_IN
        out = cls.vif_chain_prefix() + vif_uuid + cls.SUFFIX_OUT
        return {'in': in_, 'out': out}

    @classmethod
    def is_chain_name_for_rule(cls, name, group_id, is_default):
        if is_default == True:
            return name == cls.SG_DEFAULT
        else:
            return name.startswith(cls.sg_chain_name_prefix(group_id))


class RouterName:
    PROVIDER_ROUTER = 'provider_router'
    TENANT_ROUTER = 'os_project_router'


class Rule:
    OS_SG_KEY = 'os_sg_rule_id'

    @classmethod
    def properties(cls, os_sg_rule_id):
        return {cls.OS_SG_KEY: str(os_sg_rule_id)}

