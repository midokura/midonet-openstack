# Copyright (C) 2011 Midokura KK
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

"""The Midonet Floating IP extension."""

import webob
from webob import exc
from nova import utils
from nova import db

from nova import flags
from nova import log as logging
from nova.api.openstack import extensions
from nova.api.openstack import wsgi
import netaddr

FLAGS = flags.FLAGS
#flags.DEFINE_string('network_api', 'api.MidoAPI',
#                    'Nova netowrk API for MidoNet')

LOG = logging.getLogger('nova.api.openstack.contrib.floating_ips')



def _get_metadata():
    metadata = {
        "attributes": {
            "floating_ip": [
                "id",
                "ip",
                "instance_id",
                "fixed_ip",
                ]}}


    return metadata

class MidoFloatingIPController(object):
    """The Network API controller for the OpenStack API."""

    def __init__(self):
        self.network_api = utils.import_object(FLAGS.network_api)
        super(MidoFloatingIPController, self).__init__()

    def create(self, req, body=None):
        if not body:
            raise exc.HTTPUnprocessableEntity()
        if not 'range' in body:
            raise exc.HTTPUnprocessableEntity()

        context = req.environ['nova.context']
        range_ = body['range']

        for address in netaddr.IPNetwork(range_):
            print address
            db.floating_ip_create(context,
                                  {'address': str(address)})
        return {"create":"done"}


    def delete(self, req, body=None):
        print " DELETE ", req, body
        if not body:
            raise exc.HTTPUnprocessableEntity()
        if not 'range' in body:
            raise exc.HTTPUnprocessableEntity()

        context = req.environ['nova.context']
        range_ = body['range']


        for address in netaddr.IPNetwork(range_):
            db.floating_ip_destroy(context,
                                   str(address))
        return {"delete": "done"}


class Mido_floating_ips(extensions.ExtensionDescriptor):
    def __init__(self):
        super(Mido_floating_ips, self).__init__()

    def get_name(self):
        return "mido-floating-ips"

    def get_alias(self):
        return "mido-floating-ips"

    def get_description(self):
        return "Midonet floating ip API"

    def get_namespace(self):
        return "http://docs.openstack.org/ext/mido-floating-ips/api/v1.1"

    def get_updated(self):
        return "2011-09-26T00:00:00+00:00"

    def get_resources(self):
        print "-------------------->",self.__class__
        resources = []

        metadata = _get_metadata()
        body_serializers = {
            'application/xml': wsgi.XMLDictSerializer(metadata=metadata,
                                                      xmlns=wsgi.XMLNS_V11)}
        serializer = wsgi.ResponseSerializer(body_serializers, None)
        res = extensions.ResourceExtension(
            'mido-floating-ips',
            controller=MidoFloatingIPController(),
            serializer=serializer)
        resources.append(res)

        return resources
