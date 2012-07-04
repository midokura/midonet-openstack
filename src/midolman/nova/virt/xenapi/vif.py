# Copyright (C) 2012 Midokur Japan, KK
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

from nova.virt.xenapi.vif import XenAPIOpenVswitchDriver
from midolman.nova.network import midonet_connection
from midonet.api import PortType


class XenAPIMidoNetDriver(XenAPIOpenVswitchDriver):
    """VIF driver for MidoNetDriver with XenAPI."""

    def __init__(self, xenapi_session):
        super(self.__class__, self).__init__(xenapi_session)
        self.mido_conn = midonet_connection.get_connection()

    def plug(self, instance, vif, vm_ref=None, device=None):
        vif_rec = super(self.__class__, self).plug(instance, vif, vm_ref, device)

        tenant_id = vif['network']['meta']['tenant_id']
        bridge_id = vif['network']['id']
        subnet = vif['network']['subnets'][0]['cidr'].replace('/', '_')
        mac = vif_rec['MAC']
        ip = vif['network']['subnets'][0]['ips'][0]['address']
        name = vif['id']

        # Create DHCP host
        response, content = self.mido_conn.dhcp_hosts().create(tenant_id, bridge_id, subnet, mac, ip, name)
        # List Bridge ports
        response, bridge_ports = self.mido_conn.bridge_ports().list(tenant_id, bridge_id)

        # Search for the port that has the vif attached
        found = False
        for bp in bridge_ports:
            if bp['type'] == PortType.MATERIALIZED_BRIDGE and bp['vifId'] == name:
                port_id = bp['id']
                found = True
                break
        assert found

        vif_rec['other_config'] = {'midonet-vnet': port_id}
        return vif_rec
