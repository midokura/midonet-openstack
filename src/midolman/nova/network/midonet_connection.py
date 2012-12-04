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
from nova import log as logging
from nova.openstack.common import cfg

from midonet.auth.keystone import KeystoneAuth
from midonet.client.mgmt import MidonetMgmt
from midonet.client.web_resource import WebResource
import midolman.common.flags as mido_flags

FLAGS = flags.FLAGS
FLAGS.register_opts(mido_flags.midonet_opts)
LOG = logging.getLogger(__name__)

mido_conn = None

def get_connection():
    global mido_conn
    if mido_conn == None:
        auth = KeystoneAuth(FLAGS.midonet_keystone_uri,
                            FLAGS.midonet_admin_user,
                            FLAGS.midonet_admin_password,
                            tenant_id=FLAGS.midonet_provider_tenant_id)
        web_resource = WebResource(auth)
        mido_conn = MidonetMgmt(FLAGS.midonet_uri, web_resource, LOG)
    return mido_conn
