# Copyright (C) 2012 Midokura KK
# Copyright 2011 OpenStack LLC.
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

"""MidoNet VIF driver for Libvirt."""

from nova import flags
from nova import utils
from nova.openstack.common import cfg
from nova.openstack.common import log as logging
from nova.virt import vif
from nova.virt.libvirt import config
from nova.virt.libvirt.vif import FLAGS as vif_flags
from webob import exc as w_exc

from midolman.nova.midonet_connection import get_mido_mgmt

LOG = logging.getLogger('nova...' + __name__)

midonet_vif_driver_opts = [
    cfg.StrOpt('midonet_host_uuid_path',
               default='/etc/midolman/host_uuid.properties',
               help='path to midonet host uuid file'),
    ]

FLAGS = flags.FLAGS
FLAGS.register_opts(midonet_vif_driver_opts)


class MidonetVifDriver(vif.VIFDriver):

    def __init__(self, **kwargs):
        self.mido_mgmt = get_mido_mgmt()

    def _get_dev_name(self, instance_uuid, vport_id):
        """Returns tap device name, which includes instance id and vport id."""
        dev_name = "osvm-" + instance_uuid[:4] + '-' + vport_id[:4]
        return dev_name

    def _get_host_uuid(self):
        """
        Get MidoNet host id from host_uuid.properties file.
        """

        f = open(FLAGS.midonet_host_uuid_path)
        lines = f.readlines()
        host_uuid = filter(lambda x: x.startswith('host_uuid='),
                         lines)[0].strip()[len('host_uuid='):]
        return host_uuid

    def _device_exists(self, device):
        """Check if ethernet device exists."""
        (_out, err) = utils.execute('ip', 'link', 'show', 'dev', device,
                                    check_exit_code=False, run_as_root=True)
        return not err

    def _create_vif(self, instance_uuid, mapping, create_device):
        host_dev_name = self._get_dev_name(instance_uuid, mapping['vif_uuid'])
        peer_dev_name = None
        if FLAGS.libvirt_type == 'lxc':
            peer_dev_name = 'lv' + host_dev_name[4:]

        if not create_device:
            return (host_dev_name, peer_dev_name)

        if FLAGS.libvirt_type == 'kvm' or FLAGS.libvirt_type == 'qemu':
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

    def _delete_tap(self, dev_name):
        utils.execute('ip', 'link', 'del', dev_name, run_as_root=True)

    def plug(self, instance, vif, **kwargs):
        """
        Creates if-vport mapping and returns interface data for the caller.
        """
        LOG.debug('instance=%r, vif=%r, kwargs=%r', instance, vif, kwargs)

        network, mapping = vif  # extract data into legacy nova param names

        vport_id = vif[1]['vif_uuid']
        host_dev_name = self._get_dev_name(instance['uuid'], vport_id)

        # create vif (tap for kvm/qemu, veth for lxc) if not found
        create_device = True
        if self._device_exists(host_dev_name):
            create_device = False
        host_dev_name, peer_dev_name = self._create_vif(
            instance['uuid'], mapping, create_device)

        # create if-vport mapping.
        host_uuid = self._get_host_uuid()
        try:
            host = self.mido_mgmt.get_host(host_uuid)
        except w_exc.HTTPError as e:
            LOG.error('Failed to create a if-vport mapping on host=%s',
                      host_uuid)
            raise e
        host.add_host_interface_port().port_id(vport_id)\
            .interface_name(host_dev_name).create()

        # construct data for libvirt xml and return it.
        conf = config.LibvirtConfigGuestInterface()
        if vif_flags.libvirt_use_virtio_for_bridges:
            conf.model = 'virtio'
        conf.net_type = 'ethernet'
        if FLAGS.libvirt_type == 'kvm' or FLAGS.libvirt_type == 'qemu':
            conf.target_dev = host_dev_name
        elif FLAGS.libvirt_type == 'lxc':
            conf.target_dev = peer_dev_name
        conf.script = ''
        conf.mac_addr = vif[1]['mac']
        return conf

    def unplug(self, instance, vif, **kwargs):
        """
        Tear down the tap interface.
        Note that we don't need to tear down the if-vport mapping since,
        at this point, it should've been deleted when vport was deleted
        from Nova.
        """
        LOG.debug('instance=%r, vif=%r, kwargs=%r', instance, vif, kwargs)
        try:
            vport_id = vif[1]['vif_uuid']
            dev_name = self._get_dev_name(instance['uuid'], vport_id)

            # tear down the tap if it exists.
            if self._device_exists(dev_name):
                self._delete_tap(dev_name)
        except:
            # Swallowing exception to let the instance go.
            LOG.exception(_("Failed while unplugging vif=%s", dev_name),
                          instance=instance)
