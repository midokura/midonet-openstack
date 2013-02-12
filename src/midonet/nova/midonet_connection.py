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

from midonetclient.api import MidonetApi
from midonetclient.web_resource import WebResource
from midonetclient.auth.keystone import KeystoneAuth

LOG = logging.getLogger('nova...' + __name__)

midonet_opts = [
    cfg.StrOpt('midonet_uri',
               default='http://localhost:8080/midonet-api',
               help='URI for MidoNet REST API server.'),
    ]

CONF = cfg.CONF
CONF.register_opts(midonet_opts)

mido_api = None


def get_mido_api():
    global mido_api
    if mido_api == None:
        auth = KeystoneAuth(uri=quantum_conf.quantum_admin_auth_url,
                            username=quantum_conf.quantum_admin_username,
                            password=quantum_conf.quantum_admin_password,
                            tenant_name=quantum_conf.quantum_admin_tenant_name)
        web_resource = WebResource(auth, logger=LOG)

        mido_api = MidonetApi(midonet_uri=CONF.midonet_uri,
                                web_resource=web_resource, logger=LOG)

    return mido_api
