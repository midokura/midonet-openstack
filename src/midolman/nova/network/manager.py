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

from nova.network.quantum.manager import QuantumManager

from nova import flags
from nova import log as logging
from nova.openstack.common import cfg

FLAGS = flags.FLAGS
LOG = logging.getLogger(__name__)

class MidonetManager(QuantumManager):

    # Mostly copy-n-pasted from quantum manager
    # Only difference is to pass gateway address and cider to the quantum plugin
    def create_networks(self, context, label, cidr, multi_host, num_networks,
                        network_size, cidr_v6, gateway, gateway_v6, bridge,
                        bridge_interface, dns1=None, dns2=None, uuid=None,
                        **kwargs):
        """Unlike other NetworkManagers, with QuantumManager, each
           create_networks calls should create only a single network.

           Two scenarios exist:
                - no 'uuid' is specified, in which case we contact
                  Quantum and create a new network.
                - an existing 'uuid' is specified, corresponding to
                  a Quantum network created out of band.

           In both cases, we initialize a subnet using the IPAM lib.
        """
        # Enforce Configuration sanity.
        #
        # These flags are passed in from bin/nova-manage. The script
        # collects the arguments and then passes them in through this
        # function call. Note that in some cases, the script pre-processes
        # the arguments, and sets them to a default value if a parameter's
        # value was not specified on the command line. For pre-processed
        # parameters, the most effective check to see if the user passed it
        # in is to see if is different from the default value. (This
        # does miss the use case where the user passes in the default value
        # on the command line -- but it is unavoidable.)
        if multi_host != FLAGS.multi_host:
            # User specified it on the command line.
            raise Exception(_("QuantumManager does not use 'multi_host'"
                              " parameter."))

        if num_networks != 1:
            raise Exception(_("QuantumManager requires that only one"
                              " network is created per call"))

        if network_size != int(FLAGS.network_size):
            # User specified it on the command line.
            LOG.warning("Ignoring unnecessary parameter 'network_size'")

        if kwargs.get('vlan_start', None):
            if kwargs['vlan_start'] != int(FLAGS.vlan_start):
                # User specified it on the command line.
                LOG.warning(_("QuantumManager does not use 'vlan_start'"
                              " parameter."))

        if kwargs.get('vpn_start', None):
            if kwargs['vpn_start'] != int(FLAGS.vpn_start):
                # User specified it on the command line.
                LOG.warning(_("QuantumManager does not use 'vpn_start'"
                              " parameter."))

        if bridge is not None and len(bridge) > 0:
            LOG.warning(_("QuantumManager does not use 'bridge'"
                          " parameter."))

        if bridge_interface is not None and len(bridge_interface) > 0:
            LOG.warning(_("QuantumManager does not use 'bridge_interface'"
                          " parameter."))

        if gateway is not None and len(gateway) > 0:
            if gateway.split('.')[3] != '1':
                raise Exception(_("QuantumManager requires a valid (.1)"
                              " gateway address."))

        q_tenant_id = kwargs["project_id"] or FLAGS.quantum_default_tenant_id
        quantum_net_id = uuid
        # If a uuid was specified with the network it should have already been
        # created in Quantum, so make sure.
        if quantum_net_id:
            if not self.q_conn.network_exists(q_tenant_id, quantum_net_id):
                    raise Exception(_("Unable to find existing quantum "
                                      "network for tenant '%(q_tenant_id)s' "
                                      "with net-id '%(quantum_net_id)s'") %
                                    locals())
        else:
            nova_id = self._get_nova_id()
            quantum_net_id = self.q_conn.create_network(q_tenant_id, label,
                                                        nova_id=nova_id,
                                                        # for midonet plugin
                                                        cidr=cidr, gateway=gateway)

        ipam_tenant_id = kwargs.get("project_id", None)
        priority = kwargs.get("priority", 0)
        # NOTE(tr3buchet): this call creates a nova network in the nova db
        self.ipam.create_subnet(context, label, ipam_tenant_id,
                                quantum_net_id, priority, cidr,
                                gateway, gateway_v6, cidr_v6, dns1, dns2)

        self._update_network_host(context, quantum_net_id)

        # Initialize forwarding
        self.l3driver.initialize_network(cidr)

        return [{'uuid': quantum_net_id}]

