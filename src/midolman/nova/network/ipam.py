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

import netaddr

from nova import db
from nova import exception
from nova import flags
from nova import ipv6
from nova import log as logging
from nova.network import manager

from nova.network.quantum.nova_ipam_lib import QuantumNovaIPAMLib
from midonet.client import MidonetClient
from midolman.nova.network import midonet_connection

LOG = logging.getLogger(__name__)
FLAGS = flags.FLAGS


def get_ipam_lib(net_man):
    return MidonetNovaIPAMLib(net_man)


class MidonetNovaIPAMLib(QuantumNovaIPAMLib):

    # Override to make a link from the tenant router to the bridge
    def create_subnet(self, context, label, tenant_id,
                      quantum_net_id, priority, cidr=None,
                      gateway=None, gateway_v6=None, cidr_v6=None,
                      dns1=None, dns2=None):
        """Re-use the basic FlatManager create_networks method to
           initialize the networks and fixed_ips tables in Nova DB.

           Also stores a few more fields in the networks table that
           are needed by Quantum but not the FlatManager.
        """
        admin_context = context.elevated()
        subnet_size = len(netaddr.IPNetwork(cidr))
        networks = manager.FlatManager.create_networks(self.net_manager,
                    admin_context, label, cidr,
                    False, 1, subnet_size, cidr_v6, gateway,
                    gateway_v6, quantum_net_id, None, dns1, dns2,
                    ipam=True)
        #TODO(tr3buchet): refactor passing in the ipam key so that
        # it's no longer required. The reason it exists now is because
        # nova insists on carving up IP blocks. What ends up happening is
        # we create a v4 and an identically sized v6 block. The reason
        # the quantum tests passed previosly is nothing prevented an
        # incorrect v6 address from being assigned to the wrong subnet

        if len(networks) != 1:
            raise Exception(_("Error creating network entry"))

        network = networks[0]
        net = {"project_id": tenant_id,
               "priority": priority,
               "uuid": quantum_net_id}
        db.network_update(admin_context, network['id'], net)

        # NOTE(tomoe): for some reason, LOG.debug doesn't work here...
        print "Debug: label: ", label
        print "Debug: teannt_id:", tenant_id
        print "Debug: quantum_net_id:", quantum_net_id
        print "Debug: gateway:", network['gateway']
        print "Debug: cidr:", cidr

        mido_conn = midonet_connection.get_connection()

        gateway = network['gateway']
        net_addr, length = cidr.split('/')
        length = int(length)
        bridge_id = quantum_net_id

        if not tenant_id:
            tenant_id = FLAGS.quantum_default_tenant_id
        tenant_router_name = FLAGS.midonet_tenant_router_name_format % tenant_id

        response, content = mido_conn.routers().list(tenant_id)
        tenant_router_id = None
        for r in content:
            if r['name'] == tenant_router_name:
                LOG.debug("Tenant Router found")
                found = True
                tenant_router_id = r['id']
        assert found

        # Create a link from the tenant router to the bridge
        response, content = mido_conn.routers().link_bridge_create(
                                        tenant_id,
                                        tenant_router_id,
                                        net_addr, length, gateway,
                                        bridge_id)
        router_port_id = content['routerPortId']

        # Create a route to the subnet in the tenant router
        response, content = mido_conn.routes().create(
                                        tenant_id,
                                        tenant_router_id,
                                        'Normal',         # type
                                        '0.0.0.0', 0,     # source
                                        net_addr, length, # destination
                                         100,             # weight
                                        router_port_id,   # next hop port
                                        None)             # next hop gateway
