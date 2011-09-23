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

"""VIF drivers for libvirt."""
import json
import pwd
import socket

from midolman.midonet import client

from nova import flags
from nova import log as logging
from nova.virt.vif import VIFDriver

_BUFFSIZE = 1024

LOG = logging.getLogger('midolman.nova.virt.libvirt.vif')

FLAGS = flags.FLAGS
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

def get_pwd_id(name):
    """Gets UID and GID from /etc/password file for the given user name.
    """
    try:
        p = pwd.getpwnam(name)
        return (p.pw_uid, p.pw_gid)
    except KeyError:
        LOG.exception('Attempted to get UID/GID of non-existent user: %s' %
                      name)
        return (None, None)

def send_data_over_tcp(data):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect((FLAGS.mido_agent_host, FLAGS.mido_agent_port))
    LOG.info("Sending %s to Net Agent" % data)
    sock.send(json.dumps(data))
    result = sock.recv(_BUFFSIZE)
    LOG.info("Net Agent returned %r" % result)
    sock.close()
    return result

def _create_tap_if(mac_address):
    uid,gid = get_pwd_id(FLAGS.mido_libvirt_user)
    res = send_data_over_tcp({'action': 'create_tap',
                              'name': FLAGS.mido_tap_format,
                              'uid': uid,
                              'gid': gid,
                              'mac_address': mac_address})
    res_dict = json.loads(res)
    if res_dict['ret_code']:
        raise ValueError('create_tap did not return valid value.')
    return res_dict['name']

def _create_ovs_port(port_id, tap_name):
    # Create a new OVS port and set its external ID to the ZK port.
    # This call should also create a bridge if it doesn't exist yet.
    res = send_data_over_tcp({'action': 'create_port',
                              'port_id': port_id,
                              'if_name': tap_name, 
                              'external_id': FLAGS.mido_router_network_id})
    res_dict = json.loads(res)
    if res_dict['ret_code']:
        raise ValueError('create_port did not return valid value.')
    return res_dict

def _activate_tap_if(tap_name):
    res = send_data_over_tcp({'action': 'activate_tap',
                              'if_name': tap_name})
    res_dict = json.loads(res)
    if res_dict['ret_code']:
        raise ValueError('activate_port did not return valid value.')
    return res_dict

def _extract_id_from_header_location(response):
    return response['location'].split('/')[-1]

class MidoNetVifDriver(VIFDriver):
    """VIF driver for MidoNet."""

    def plug(self, instance, network, mapping):

        mac_address = mapping['mac']
        router_id = network['uuid']

        # Create a tap interface
        tap_name = _create_tap_if(mac_address)

        if not router_id is None:
            network_address, network_len = network['cidr'].split('/')
            gateway = mapping['gateway']
            local_network_address = mapping['ips'][0]['ip']
            vif_id = mapping['vif_uuid']
    
            mc = client.MidonetClient(FLAGS.mido_admin_token,
                                      FLAGS.mido_api_host,
                                      FLAGS.mido_api_port,
                                      FLAGS.mido_api_app)
    
            # Create a materialized port on the router.
            response, content = mc.create_router_port(router_id,
                network_address, network_len, gateway, local_network_address, 32)
            port_id = _extract_id_from_header_location(response)
    
            # Set a route so that the fixed IP is routed to this port.
            response, content = mc.create_route(router_id, '0.0.0.0', 0, 'Normal',
                                                local_network_address, 32, port_id,
                                                None, 100);
    
            # Plug in the VIF into the port
            response, content = mc.plug_vif(port_id, vif_id)

            # Create an OVS port.
            res = _create_ovs_port(port_id, tap_name)

        # Activate the tap.
        _activate_tap_if(tap_name)

        return {
            'name': tap_name,
            'mac_address': mac_address,
            'script': ''}


    def unplug(self, instance, network, mapping):
        """No manual unplugging required."""
        pass
