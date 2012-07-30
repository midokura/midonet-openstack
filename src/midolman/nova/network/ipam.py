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
from midonet.client import MidonetClient
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
        response, content = mido_conn.dhcps().create(tenant_id, bridge_id,
                                                     net_addr, length, gateway)

        # Search tenant router
        tenant_router_name = FLAGS.midonet_tenant_router_name

        response, content = mido_conn.routers().list(tenant_id)
        tenant_router_id = None
        for r in content:
            if r['name'] == tenant_router_name:
                LOG.debug("Tenant Router found: %r", r)
                found = True
                tenant_router_id = r['id']
        assert found

        # Create a port in the tenant router
        response, content = mido_conn.router_ports().create(
                tenant_id,
                tenant_router_id,
                PortType.LOGICAL_ROUTER,
                net_addr, length,
                gateway)
        response, tenant_router_port = mido_conn.get(response['location'])
        LOG.debug('tenant_router_port=%r', tenant_router_port)

        # Create a port in the bridge
        response, content = mido_conn.bridge_ports().create(
                tenant_id,
                bridge_id,
                PortType.LOGICAL_BRIDGE)

        response, bridge_port = mido_conn.get(response['location'])
        LOG.debug('bridge_port=%r', bridge_port)

        # Link them
        response, content = mido_conn.router_ports().link(
                tenant_id,
                tenant_router_id,
                tenant_router_port['id'],
                bridge_port['id'])

        tenant_router_port_id = tenant_router_port['id']

        # Create a route to the subnet in the tenant router
        response, content = mido_conn.routes().create(
                tenant_id,
                tenant_router_id,
                'Normal',                # type
                '0.0.0.0', 0,            # source
                net_addr, length,        # destination
                100,                     # weight
                tenant_router_port_id,   # next hop port
                None)                    # next hop gateway
