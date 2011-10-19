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
from nova import flags
from nova import utils
from nova.virt.libvirt.vif import LibvirtOpenVswitchDriver

FLAGS = flags.FLAGS
flags.DEFINE_integer('mido_tap_mtu', 1500, 'MTU of tap')
flags.DEFINE_string('mido_ovs_ext_id_key', 'midolman-vnet',
                    'OVS external ID key for midolman')

class MidoNetVifDriver(LibvirtOpenVswitchDriver):
    """VIF driver for MidoNet."""

    def plug(self, instance, network, mapping):

        # Call the parent method to set up OVS
        result = super(self.__class__, self).plug(instance, network, mapping)
        dev = result['name']

        # Not ideal to do this every time, but set the MTU to something big.
        utils.execute('ip', 'link', 'set', dev, 'mtu', FLAGS.mido_tap_mtu,
                      run_as_root=True)

        # Set the external ID of the OVS port to the MidoNet port UUID.
        utils.execute('ovs-vsctl', 'set', 'port', dev,
                      'external_ids:%s=%s' % (FLAGS.mido_ovs_ext_id_key,
                                              mapping['port_id']))
        return result
