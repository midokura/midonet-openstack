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


from nova.openstack.common import cfg

midonet_opts = [
    # Midonet related settings
    cfg.StrOpt('midonet_uri',
        default='http://localhost:8080/midolmanj-mgmt',
        help='Midonet API server URI'),
    cfg.StrOpt('midonet_provider_router_id',
        default='00112233-0011-0011-0011-001122334455',
        help='UUID of Midonet provider router'),
    cfg.StrOpt('midonet_provider_router_name',
        default='provider_router',
        help='Midonet provider router'),
    cfg.StrOpt('midonet_tenant_router_name',
        default = 'os_project_router',
        help='Name of tenant router'),
    cfg.StrOpt('midonet_tenant_router_in_chain_name',
        default = 'os_project_router_in',
        help='Name of the inbound chain in tenant router'),
    cfg.StrOpt('midonet_tenant_router_out_chain_name',
        default = 'os_project_router_out',
        help='Name of the outbound chain in tenant router'),

    # Keystone related settings

    cfg.StrOpt('midonet_keystone_uri',
        default = 'http://localhost:5000/v2.0/',
        help='Keystone API endpoinnt for generating token for admin.'),
    cfg.StrOpt('midonet_admin_user',
        default = 'admin',
        help='Midonet admin user name in keystone'),
    cfg.StrOpt('midonet_admin_password',
        default = 'passw0rd',
        help='Midonet admin user name in keystone'),
    cfg.StrOpt('midonet_provider_tenant_id',
        default = 'mido_provider',
        help='Midonet provider tenant id')
]
