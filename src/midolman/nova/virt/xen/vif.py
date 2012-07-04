# Copyright (C) 2012 Midokura KK
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

from nova import context
from nova import db
from nova import flags
from nova import utils
from nova.openstack.common import cfg
from nova.virt.xenapi.vif import XenAPIOpenVswitchDriver
from nova import log as logging

from midolman.nova.network import midonet_connection
from midonet.api import PortType
from midonet.client import MidonetClient

FLAGS = flags.FLAGS
LOG = logging.getLogger(__name__)


class XenAPIMidoNetDriver(XenAPIOpenVswitchDriver):
    """VIF driver for MidoNetDriver with XenAPI."""

    def __init__(self, xenapi_session):
        super(self.__class__, self).__init__(xenapi_session)
        self.mido_conn = midonet_connection.get_connection()

    def plug(self, instance, vif, vm_ref=None, device=None):
        vif_rec = super(self.__class__, self).plug(instance, vif, vm_ref, device)
        # Get the tenant id
        tenant_id = vif['network']['meta']['tenant_id']
        # Get the bridge id
        bridge_id = vif['network']['id']
        # Get the subnet
        subnet = vif['network']['subnets'][0]['cidr'].replace('/', '_')
        # Get the MAC address
        mac = vif_rec['MAC']
        # Get the vif id
        name = vif['id']
        # Get ip address
        ip = vif['network']['subnets'][0]['ips'][0]['address']

        # Create DHCP host
        response, content = self.mido_conn.dhcp_hosts().create(tenant_id, bridge_id, subnet, mac, ip, name)
        # List Bridge ports
        response, bridge_ports = self.mido_conn.bridge_ports().list(tenant_id, bridge_id)

        # Search for the port that has the vif attached
        found = False
        for bp in bridge_ports:
            if bp['type'] != PortType.MATERIALIZED_BRIDGE:
                continue
            if bp['vifId'] == name:
                port_id = bp['id']
                found = True
                break
        assert found

        vif_rec['other_config'] = {'midonet-vnet': port_id}

        LOG.debug('vif_rec %s' % vif_rec)
        return vif_rec
