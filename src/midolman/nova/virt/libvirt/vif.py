# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (C) 2011 Midokura Japan KK
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

    def plug(self, instance, network, mapping):
        LOG.debug('instance=%r, network=%r, mapping=%r', instance, network,
                                                         mapping)

        # Call the parent method to set up OVS
        result = super(self.__class__, self).plug(instance, network, mapping)
        dev = result['name']

        # Not ideal to do this every time, but set the MTU to something big.
        utils.execute('ip', 'link', 'set', dev, 'mtu', FLAGS.midonet_tap_mtu,
                      run_as_root=True)

        (tenant_id, bridge_id, subnet, mac, ip, name) = self._get_dhcp_data(
                network, mapping)

        response, content = self.mido_conn.dhcp_hosts().create(tenant_id,
                bridge_id, subnet, mac, ip, name)

        # Get port id corresponding to the vif
        response, bridge_ports = self.mido_conn.bridge_ports().list(tenant_id,
                bridge_id)
        # Search for the port that has the vif attached
        found = False
        for bp in bridge_ports:
            if bp['type'] != PortType.MATERIALIZED_BRIDGE:
                continue
            if bp['vifId'] == mapping['vif_uuid']:
                port_id = bp['id']
                found = True
                break
        assert found

        # Set the external ID of the OVS port to the Midonet port UUID.
        utils.execute('ovs-vsctl', 'set', 'port', dev,
                      'external_ids:%s=%s' % (FLAGS.midonet_ovs_ext_id_key,
                                              port_id),
                      run_as_root=True)
        return result

    def unplug(self, instance, network, mapping):
        LOG.debug('instance=%r, network=%r, mapping=%r', instance, network,
                                                         mapping)
        super(self.__class__, self).unplug(instance, network, mapping)

        (tenant_id, bridge_id, subnet, mac, ip, name) = self._get_dhcp_data(
                network, mapping)

        response, content = self.mido_conn.dhcp_hosts().delete(tenant_id,
                bridge_id, subnet, mac)
