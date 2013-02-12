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

from nova import flags
from nova.openstack.common import log as logging
from nova.openstack.common import cfg
from nova.network.quantumv2.api import FLAGS as quantum_flags

from midonet.client.mgmt import MidonetMgmt
from midonet.client.web_resource import WebResource
from midonet.auth.keystone import KeystoneAuth

LOG = logging.getLogger('nova...' + __name__)

midonet_opts = [
    cfg.StrOpt('midonet_uri',
               default='http://localhost:8080/midolmanj-mgmt',
               help='URI for MidoNet REST API server.'),
    ]

FLAGS = flags.FLAGS
FLAGS.register_opts(midonet_opts)

mido_mgmt = None

def get_mido_mgmt():
    global mido_mgmt
    if mido_mgmt == None:
        auth = KeystoneAuth(uri=quantum_flags.quantum_admin_auth_url,
                            username=quantum_flags.quantum_admin_username,
                            password=quantum_flags.quantum_admin_password,
                            tenant_name=quantum_flags.quantum_admin_tenant_name)
        web_resource = WebResource(auth, logger=LOG)

        mido_mgmt = MidonetMgmt(midonet_uri=FLAGS.midonet_uri,
                                web_resource=web_resource, logger=LOG)

    return mido_mgmt
