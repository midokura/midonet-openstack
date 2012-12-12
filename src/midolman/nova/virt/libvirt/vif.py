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

"""VIF driver for Midonet."""
from nova import context
from nova import db
from nova import flags
from nova import log as logging
from nova import utils
from nova.openstack.common import cfg
from nova.virt.libvirt.vif import LibvirtOpenVswitchDriver

from midolman.nova.network import midonet_connection
import midonet.client.port_type as PortType


midonet_opts = [
    cfg.IntOpt('midonet_tap_mtu',
               default=1500,
               help='Mtu of tap'),
    cfg.StrOpt('midonet_ovs_ext_id_key',
               default='midolman-vnet',
               help='OVS external ID key for midolman')
]

FLAGS = flags.FLAGS
FLAGS.register_opts(midonet_opts)
# Add 'nova' prefix for nova's logging setting
LOG = logging.getLogger('nova...' + __name__)


class MidonetVifDriver(LibvirtOpenVswitchDriver):
    """VIF driver for Midonet."""

    # Super class doesn't have ctor, so it doesn't need to call super()
    def __init__(self):
        self.mido_conn = midonet_connection.get_connection()

    def _get_dhcp_data(self, network, mapping):

        # Get tenant id from db
        network_ref = db.network_get_by_uuid(context.get_admin_context(),
                                             network['id'])
        tenant_id = network_ref['project_id']
        if not tenant_id:
            tenant_id = FLAGS.quantum_default_tenant_id

        # params for creating dhcp host
        bridge_id = network['id']
        subnet = network['cidr'].replace('/', '_')
        mac = mapping['mac']
        ip = mapping['ips'][0]['ip']
        name = mapping['vif_uuid']

        return (tenant_id, bridge_id, subnet, mac, ip, name)

    def _get_dev_name(self, instance_uuid, vif_uuid):
        dev_name = "osvm-" + instance_uuid[:4] + '-' + vif_uuid[:4]
        return dev_name

    def _get_vport_id(self, tenant_id, bridge_id, vif_uuid):
        # Get port id corresponding to the vif
        bridge = self.mido_conn.get_bridge(bridge_id)
        bridge_ports = bridge.get_ports()

        # Search for the port that has the vif attached
        found = False
        for bp in bridge_ports:
            if bp.get_type() != PortType.EXTERIOR_BRIDGE:
                continue
            if bp.get_vif_id() == vif_uuid:
                port_id = bp.get_id()
                found = True
                break
        assert found
        return port_id

    def _get_host_uuid(self):
        # quick-n-dirty for now
        f = open('/etc/midolman/host_uuid.properties')
        lines = f.readlines()
        host_uuid=filter(lambda x: x.startswith('host_uuid='),
                         lines)[0].strip()[len('host_uuid='):]
        return host_uuid

    def _create_vif(self, instance_uuid, mapping, create_device):
        host_dev_name = self._get_dev_name(instance_uuid, mapping['vif_uuid'])
        peer_dev_name = None
        if FLAGS.libvirt_type == 'lxc':
            peer_dev_name = 'lv' + host_dev_name[4:]

        if not create_device:
            return (host_dev_name, peer_dev_name)

        if FLAGS.libvirt_type == 'kvm':
            utils.execute('ip', 'tuntap', 'add', host_dev_name, 'mode', 'tap',
                          run_as_root=True)
        elif FLAGS.libvirt_type == 'lxc':
            utils.execute('ip', 'link', 'add', 'name', host_dev_name, 'type',
                          'veth', 'peer', 'name', peer_dev_name,
                          run_as_root=True)
            utils.execute('ip', 'link', 'set', 'dev', peer_dev_name, 'address',
                          mapping['mac'], run_as_root=True)
        utils.execute('ip', 'link', 'set', host_dev_name, 'up',
                      run_as_root=True)
        return (host_dev_name, peer_dev_name)

    def _device_exists(self, device):
        """Check if ethernet device exists."""
        (_out, err) = utils.execute('ip', 'link', 'show', 'dev', device,
                                    check_exit_code=False, run_as_root=True)
        return not err

    def plug(self, instance, network, mapping):
        LOG.debug('instance=%r, network=%r, mapping=%r', instance, network,
                                                         mapping)
        create_device = True
        if self._device_exists(host_dev_name):
            create_device = False
        host_dev_name, peer_dev_name = self._create_vif(
            instance['uuid'], mapping, create_device)
        result = {}
        if peer_dev_name:
            result['name'] = peer_dev_name
        else:
            result['name'] = host_dev_name
        result['mac_address'] = mapping['mac']
        result['script'] = ''

        if not create_device:
            return result

        (tenant_id, bridge_id, subnet, mac, ip, name) = self._get_dhcp_data(
                network, mapping)

        # Check IP address and Mac Address for Live Migration
        bridge = self.mido_conn.get_bridge(bridge_id)
        dhcp_subnet = bridge.get_dhcp_subnet(subnet)
        dhcp_hosts = dhcp_subnet.get_dhcp_hosts()
        dhcp_host_exist = False
        for dhcp in dhcp_hosts:
            if dhcp.get_mac_addr() == mac and dhcp.get_ip_addr() == ip:
                 dhcp_host_exist = True
                 break

        if not dhcp_host_exist:
            dhcp_subnet.add_dhcp_host().name(name).ip_addr(ip).mac_addr(
                mac).create()


        host_uuid = self._get_host_uuid()
        port_id = self._get_vport_id(tenant_id, bridge_id, mapping['vif_uuid'])
        host = self.mido_conn.get_host(host_uuid)
        host.add_host_interface_port().interface_name(host_dev_name).port_id(
            port_id).create()

        return result

    def unplug(self, instance, network, mapping):
        LOG.debug('instance=%r, network=%r, mapping=%r', instance, network,
                                                         mapping)

        (tenant_id, bridge_id, subnet, mac, ip, name) = self._get_dhcp_data(
                network, mapping)

        bridge = self.mido_conn.get_bridge(bridge_id)
        dhcp_subnet = bridge.get_dhcp_subnet(subnet)
        dhcp_hosts = dhcp_subnet.get_dhcp_hosts()
        dhcp_host_exist = False
        for dhcp in dhcp_hosts:
            if dhcp.get_mac_addr() == mac and dhcp.get_ip_addr() == ip:
                 dhcp_host_exist = True
                 break

        if dhcp_host_exist:
            dhcp.delete()

        dev_name = self._get_dev_name(instance['uuid'], mapping['vif_uuid'])
        if self._device_exists(dev_name):
            utils.execute('ip', 'link', 'delete', dev_name, run_as_root=True)


