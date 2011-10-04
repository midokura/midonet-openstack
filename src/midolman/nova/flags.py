# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (C) 2011 Midokura KK
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

flags.DEFINE_string('mido_admin_token', '999888777666',
                    'Token to use for MidoNet API.')
flags.DEFINE_string('mido_tap_format', 'midotap%d',
                    'Tap name for Midonet.')
flags.DEFINE_string('mido_agent_host', 'localhost',
                    'The host that midonet agent is listneing on.')
flags.DEFINE_integer('mido_agent_port', 8999,
                     'The port that midonet agent is listening on.')
flags.DEFINE_string('mido_libvirt_user', 'libvirt-qemu',
                    'Libvirt user on the system.')
flags.DEFINE_string('mido_router_network_id',
                    'd66a5180-e322-11e0-9572-0800200c9a66',
                    'VRN id')
flags.DEFINE_string('network_api', 'api.MidoAPI',
                    'Nova netowrk API for MidoNet')
flags.DEFINE_string('mido_provider_router_id',
                    '3cc61b4a-5845-4c9a-bd5c-2f7851b72f66',
                    'UUID of the provider router in MidoNet')
flags.DEFINE_string('mido_link_port_network_address',
                    '10.0.0.0',
                    'Network address for MidoNet logical ports')
flags.DEFINE_integer('mido_link_port_network_len', 30,
                     'Network address length for MidoNet logical ports')
flags.DEFINE_string('mido_link_local_port_network_address',
                    '10.0.0.1',
                    'Network address for MidoNet local logical ports')
flags.DEFINE_string('mido_link_peer_port_network_address',
                    '10.0.0.2',
                    'Network address for MidoNet logical port peer')
flags.DEFINE_string('mido_api_host', '127.0.0.1',
                    'API host of MidoNet')
flags.DEFINE_integer('mido_api_port', 80, 'Port of the MidoNet API server')
flags.DEFINE_string('mido_api_app', 'midolmanj-mgmt',
                    'App name of the API server.')

