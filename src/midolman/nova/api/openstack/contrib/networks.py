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

"""The Network extension."""

import webob
from webob import exc
from nova import utils

from nova import exception
from nova import flags
from nova import log as logging
from nova import network
from nova import rpc
from nova.api.openstack import faults
from nova.api.openstack import extensions
from nova.api.openstack import wsgi

import sys

FLAGS = flags.FLAGS
flags.DEFINE_string('network_api', 'api.MidoAPI',
                    'Nova netowrk API for MidoNet')

LOG = logging.getLogger('nova.api.openstack.contrib.network')


def _translate_network_view(network):
    if network:
        result = {'id': network['uuid'], "cidr": network['netmask'], "bridge": network['bridge'],
                  "gateway": network['gateway'], "broadcast": network['broadcast'], "dns1": network['dns1'],
                  "vlan": network['vlan'], "vpn_public_address": network['vpn_public_address'],
                  "vpn_public_port": network['vpn_public_port'], "vpn_private_address": network['vpn_private_address'],
                  "dhcp_start": network['dhcp_start'], "project_id": network['project_id'], "host": network['host'], 
                  "cider_v6": network['cidr_v6'], "gateway_v6": network['gateway_v6'], "label": network['label'],
                  "netmask_v6": network['netmask_v6'], "bridge_interface": network['bridge_interface'], 
                  "multi_host": network['multi_host'], "dns2": network['dns2'], "priority": network['priority']}
    else:
        result = {}
    
    return {'network': result}


def _get_metadata():
    metadata = {
        "attributes": {
                'networks': ["id", "cidr", "netmask", "bridge", "gateway", 
                             "broadcast", "dns1", "vlan", "vpn_public_address", 
                             "vpn_public_port", "vpn_private_address", 
                             "dhcp_start", "project_id", "host", "cidr_v6", 
                             "gateway_v6", "label", "netmask_v6", 
                             "bridge_interface", "multi_host", "dns2", 
                             "uuid", "priority"]}}
    return metadata

class NetworkController(object):
    """The Network API controller for the OpenStack API."""

    def __init__(self):
         self.network_api = utils.import_object(FLAGS.network_api)
         super(NetworkController, self).__init__()

    def create(self, req, body=None):
        if not body:
            raise exc.HTTPUnprocessableEntity()

        if not 'network' in body:
            raise exc.HTTPUnprocessableEntity()

        context = req.environ['nova.context']
        network_dict = body['network']
        net = self.network_api.create_network(context, **network_dict)
        return _translate_network_view(net)

    def show(self, req, id):
        context = req.environ['nova.context']
        network = self.network_api.get_network(context, id)
        return _translate_network_view(network)

    def delete(self, req, id):
        context = req.environ['nova.context']

        return webob.exc.HTTPNotImplemented()


class Networks(extensions.ExtensionDescriptor):
    def __init__(self):
        super(Networks, self).__init__()

    def get_name(self):
        return "networks"

    def get_alias(self):
        return "networks"

    def get_description(self):
        return "Network API"

    def get_namespace(self):
        return "http://docs.openstack.org/ext/networks/api/v1.1"

    def get_updated(self):
        return "2011-09-16T00:00:00+00:00"

    def get_resources(self):
        resources = []

        metadata = _get_metadata()
        body_serializers = {
            'application/xml': wsgi.XMLDictSerializer(metadata=metadata,
                                                      xmlns=wsgi.XMLNS_V11)}
        serializer = wsgi.ResponseSerializer(body_serializers, None)
        res = extensions.ResourceExtension(
            'os-networks',
            controller=NetworkController(),
            serializer=serializer)
        resources.append(res)

        return resources
