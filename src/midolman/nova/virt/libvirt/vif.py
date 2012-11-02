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
from midonet.api import PortType


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
        response, bridge_ports = self.mido_conn.bridge_ports().list(tenant_id,
                bridge_id)

        # Search for the port that has the vif attached
        found = False
        for bp in bridge_ports:
            if bp['type'] != PortType.MATERIALIZED_BRIDGE:
                continue
            if bp['vifId'] == vif_uuid:
                port_id = bp['id']
                found = True
                break
        assert found
        return port_id

    def _get_host_uuid(self):
        # quick-n-dirty for now
        f = open('/etc/midolman/host_uuid.properties')
        lines = f.readlines()
        host_uuid=filter(lambda x: x.startswith('host_uuid='), lines)[0].strip()[len('host_uuid='):]
        return host_uuid

    def plug(self, instance, network, mapping):
        LOG.debug('instance=%r, network=%r, mapping=%r', instance, network,
                                                         mapping)
        dev_name = self._get_dev_name(instance['uuid'], mapping['vif_uuid'])
        utils.execute('ip', 'tuntap', 'add', dev_name, 'mode', 'tap', run_as_root=True)
        utils.execute('ip', 'link', 'set', dev_name, 'up', run_as_root=True)

        result = {}
        result['name'] = dev_name
        result['mac_address'] = mapping['mac']
        result['script'] = ''


        # Not ideal to do this every time, but set the MTU to something big.
        utils.execute('ip', 'link', 'set', dev_name, 'mtu', FLAGS.midonet_tap_mtu,
                      run_as_root=True)

        (tenant_id, bridge_id, subnet, mac, ip, name) = self._get_dhcp_data(
                network, mapping)

        # Check IP address and Mac Address for Live Migration
        response, dhcp_hosts = self.mido_conn.dhcp_hosts().list(tenant_id, bridge_id, subnet)
        dhcp_host_exist = False
        for dhcp in dhcp_hosts:
            if dhcp['macAddr'] == mac and dhcp['ipAddr'] == ip:
                 dhcp_host_exist = True
                 break

        if not dhcp_host_exist:
            response, content = self.mido_conn.dhcp_hosts().create(tenant_id,
                bridge_id, subnet, mac, ip, name)


        host_uuid = self._get_host_uuid()
        port_id = self._get_vport_id(tenant_id, bridge_id, mapping['vif_uuid'])
        self.mido_conn.hosts().add_interface_port_map(host_uuid, port_id, dev_name)

        return result

    def unplug(self, instance, network, mapping):
        LOG.debug('instance=%r, network=%r, mapping=%r', instance, network,
                                                         mapping)

        (tenant_id, bridge_id, subnet, mac, ip, name) = self._get_dhcp_data(
                network, mapping)

        response, content = self.mido_conn.dhcp_hosts().delete(tenant_id,
                bridge_id, subnet, mac)

        port_id = self._get_vport_id(tenant_id, bridge_id, mapping['vif_uuid'])

        host_uuid = self._get_host_uuid()
        self.mido_conn.hosts().del_interface_port_map(host_uuid, port_id)

        dev_name = self._get_dev_name(instance['uuid'], mapping['vif_uuid'])
        utils.execute('ip', 'link', 'delete', dev_name, run_as_root=True)


