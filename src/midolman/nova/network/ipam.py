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

import netaddr

from nova import db
from nova import exception
from nova import flags
from nova import ipv6
from nova import log as logging
from nova.network import manager

from nova.network.quantum.nova_ipam_lib import QuantumNovaIPAMLib
from midonet.api import PortType
from midolman.nova.network import midonet_connection

# Add 'nova' prefix for nova's logging setting
LOG = logging.getLogger('nova...' + __name__)
FLAGS = flags.FLAGS


def get_ipam_lib(net_man):
    return MidonetNovaIPAMLib(net_man)


class MidonetNovaIPAMLib(QuantumNovaIPAMLib):

    # Override to make a link from the tenant router to the bridge
    def create_subnet(self, context, label, tenant_id,
                      quantum_net_id, priority, cidr=None,
                      gateway=None, gateway_v6=None, cidr_v6=None,
                      dns1=None, dns2=None):
        super(self.__class__, self).create_subnet(context, label, tenant_id,
                                                  quantum_net_id, priority,
                                                  cidr, gateway, gateway_v6,
                                                  cidr_v6, dns1, dns2)
        network = db.network_get_by_uuid(context.elevated(), quantum_net_id)
        LOG.debug("label: %r ", label)
        LOG.debug("teannt_id: %r", tenant_id)
        LOG.debug("quantum_net_id: %r", quantum_net_id)
        LOG.debug("gateway: %r", network['gateway'])
        LOG.debug("cidr: %r", cidr)

        mido_conn = midonet_connection.get_connection()

        gateway = network['gateway']
        net_addr, length = cidr.split('/')
        length = int(length)
        bridge_id = quantum_net_id

        if not tenant_id:
            tenant_id = FLAGS.quantum_default_tenant_id

        # Add dhcp information to the bridge
        bridge = mido_conn.get_bridge(bridge_id)
        bridge.add_dhcp_subnet().subnet_prefix(net_addr).subnet_length(
            length).default_gateway(gateway).create()

        # Search tenant router
        tenant_router_name = FLAGS.midonet_tenant_router_name

        content = mido_conn.get_routers({'tenant_id':tenant_id})
        tenant_router_id = None
        for r in content:
            if r.get_name() == tenant_router_name:
                LOG.debug("Tenant Router found: %r", r)
                found = True
                tenant_router_id = r.get_id()
        assert found

        # Create a port in the tenant router
        router = mido_conn.get_router(tenant_router_id)
        tenant_router_port = router.add_interior_port().port_address(
            gateway).network_address(net_addr).network_length(length).create()
        LOG.debug('tenant_router_port=%r', tenant_router_port)

        # Create a port in the bridge
        bridge = mido_conn.get_bridge(bridge_id)
        bridge_port = bridge.add_interior_port().create()
        LOG.debug('bridge_port=%r', bridge_port)

        # Link them
        bridge_port.link(tenant_router_port.get_id())

        # Create a route to the subnet in the tenant router
        router.add_route().type('Normal').src_network_addr(
            '0.0.0.0').src_network_length(0).dst_network_addr(
            net_addr).dst_network_length(length).weight(100).next_hop_port(
                tenant_router_port.get_id()).create()
