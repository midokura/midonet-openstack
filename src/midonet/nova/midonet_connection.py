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

from nova.openstack.common import log as logging
from nova.openstack.common import cfg
from nova.network.quantumv2.api import CONF as quantum_conf

from midonetclient import api

LOG = logging.getLogger('nova...' + __name__)

midonet_opts = [
    cfg.StrOpt('midonet_uri',
               default='http://localhost:8080/midonet-api',
               help='URI for MidoNet REST API server.'),
    ]

midonet_opts = [
    cfg.StrOpt('midonet_uri', default='http://localhost:8080/midonet-api',
               help=_('MidoNet API server URI.')),
    cfg.StrOpt('username', default='admin',
               help=_('MidoNet admin username.')),
    cfg.StrOpt('password', default='passw0rd',
               help=_('MidoNet admin password.')),
    cfg.StrOpt('project_id',
               default='77777777-7777-7777-7777-777777777777',
               help=_('ID of the project that MidoNet admin user'
                      'belongs to.')),
    cfg.StrOpt('provider_router_id',
               default=None,
               help=_('Virtual provider router ID.')),
    cfg.StrOpt('metadata_router_id',
               default=None,
               help=_('Virtual metadata router ID.')),
    cfg.StrOpt('mode',
               default='dev',
               help=_('For development mode.'))
]

CONF = cfg.CONF
CONF.register_opts(midonet_opts, 'MIDONET')
mido_api = None


def get_mido_api():
    global mido_api
    if mido_api == None:
        mido_api = api.MidonetApi(CONF.MIDONET.midonet_uri,
                                  CONF.MIDONET.username,
                                  CONF.MIDONET.password,
                                  CONF.MIDONET.project_id)

    return mido_api
