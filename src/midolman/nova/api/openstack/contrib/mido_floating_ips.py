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
from nova import db
from nova import exception

from nova import log as logging
from nova.api.openstack import extensions
from nova.api.openstack import wsgi
import netaddr

LOG = logging.getLogger('nova.api.openstack.contrib.mido_floating_ips')


class MidoFloatingIPController(object):
    """The Midonet Floating IP  API controller"""

    def __init__(self):
        super(MidoFloatingIPController, self).__init__()

    def create(self, req, body=None):
        if not body:
            raise exc.HTTPUnprocessableEntity()
        if not 'cidr' in body:
            raise exc.HTTPUnprocessableEntity()

        context = req.environ['nova.context']
        cidr = body['cidr']

        for address in netaddr.IPNetwork(cidr):
            db.floating_ip_create(context,
                                  {'address': str(address)})

    def index(self, req):
        context = req.environ['nova.context']
        floating_ips = []
        try:
            floating_ips = db.floating_ip_get_all(context)
        except exception.NoFloatingIpsDefined:
            # just fall through and return empty content
            LOG.debug("No Floating Ip is defined")

        entries = []
        for ip in floating_ips:
            instance = None
            if ip['fixed_ip']:
                instance = ip['fixed_ip']['instance']['hostname']
            entries.append({'host':ip['host'], 'address':ip['address'], 'instance': instance})
        return {'floating_ips': entries}

    def delete_cidr(self, req, body=None):
        if not body:
            raise exc.HTTPUnprocessableEntity()
        if not 'cidr' in body:
            raise exc.HTTPUnprocessableEntity()

        context = req.environ['nova.context']
        cidr = body['cidr']


        for address in netaddr.IPNetwork(cidr):
            db.floating_ip_destroy(context,
                                   str(address))


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
        resources = []

        #metadata = _get_metadata()
        metadata = {'attributes':{}}
        body_serializers = {
            'application/xml': wsgi.XMLDictSerializer(metadata=metadata,
                                                      xmlns=wsgi.XMLNS_V11)}
        serializer = wsgi.ResponseSerializer(body_serializers, None)
        res = extensions.ResourceExtension(
            'mido-floating-ips',
            controller=MidoFloatingIPController(),
            serializer=serializer,
            collection_actions={'delete_cidr': 'POST'})
        resources.append(res)

        return resources
