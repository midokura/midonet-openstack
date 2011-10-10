# Copyright (C) 2011 Midokura KK

"""
A connection to a hypervisor through libvirt.

Supports KVM, LXC, QEMU, UML, and XEN.

**Related Flags**

:libvirt_type:  Libvirt domain type.  Can be kvm, qemu, uml, xen
                (default: kvm).
:libvirt_uri:  Override for the default libvirt URI (depends on libvirt_type).
:libvirt_xml_template:  Libvirt XML Template.
:rescue_image_id:  Rescue ami image (None = original image).
:rescue_kernel_id:  Rescue aki image (None = original image).
:rescue_ramdisk_id:  Rescue ari image (None = original image).
:injected_network_template:  Template file for injected network
:allow_same_net_traffic:  Whether to allow in project network traffic

"""

import os

import nova.virt.libvirt.connection
from nova import block_device
from nova import context as nova_context
from nova import db
from nova import exception
from nova import flags
from nova import log as logging
from nova import utils
from nova.compute import instance_types
from nova.compute import power_state
from nova.virt import driver
from nova.virt import images
import nova.virt.libvirt.connection as libvirt_conn

from midolman.nova import flags as mido_flags

FLAGS = flags.FLAGS
Template = None 
LOG = logging.getLogger('nova.virt.libvirt_conn')

def get_connection(read_only=False):
    _conn = nova.virt.libvirt.connection.get_connection(read_only)
    _late_load_cheetah()
    return BootFromCDandVolumeLibvirtConnection(read_only)

def _late_load_cheetah():
    global Template
    if Template is None:
        t = __import__('Cheetah.Template', globals(), locals(),
                       ['Template'], -1)
        Template = t.Template

def _get_eph_disk(ephemeral):
    return 'disk.eph' + str(ephemeral['num'])

class BootFromCDandVolumeLibvirtConnection(libvirt_conn.LibvirtConnection):

    def __init__(self, read_only):
        super(BootFromCDandVolumeLibvirtConnection, self).__init__(read_only)

    # tweek for supporting cdrom and volume as a boot device; ${boot} in tmpl 
    # intentionaly overriding private method to hack around.
    def _prepare_xml_info(self, instance, network_info, rescue,
                          block_device_info=None, image_info=None):
        block_device_mapping = driver.block_device_info_get_mapping(
            block_device_info)

        nics = []
        for (network, mapping) in network_info:
            nics.append(self.vif_driver.plug(instance, network, mapping))
        # FIXME(vish): stick this in db
        inst_type_id = instance['instance_type_id']
        inst_type = instance_types.get_instance_type(inst_type_id)

        if FLAGS.use_cow_images:
            driver_type = 'qcow2'
        else:
            driver_type = 'raw'

        for vol in block_device_mapping:
            vol['mount_device'] = block_device.strip_dev(vol['mount_device'])
            (vol['type'], vol['protocol'], vol['name']) = \
                self._get_volume_device_info(vol['device_path'])

        ebs_root = self._volume_in_mapping(self.default_root_device,
                                           block_device_info)

        local_device = False
        if not (self._volume_in_mapping(self.default_local_device,
                                        block_device_info) or
                0 in [eph['num'] for eph in
                      driver.block_device_info_get_ephemerals(
                          block_device_info)]):
            if instance['local_gb'] > 0:
                local_device = self.default_local_device

        ephemerals = []
        for eph in driver.block_device_info_get_ephemerals(block_device_info):
            ephemerals.append({'device_path': _get_eph_disk(eph),
                               'device': block_device.strip_dev(
                                   eph['device_name'])})

        if (image_info and image_info['disk_format'] == 'iso'):
            boot = 'cdrom'
            self.root_mount_device = '/dev/hdc'
        else:
            boot = 'hd'


        xml_info = {'type': FLAGS.libvirt_type,
                    'name': instance['name'],
                    'basepath': os.path.join(FLAGS.instances_path,
                                             instance['name']),
                    'memory_kb': inst_type['memory_mb'] * 1024,
                    'vcpus': inst_type['vcpus'],
                    'rescue': rescue,
                    'disk_prefix': self._disk_prefix,
                    'driver_type': driver_type,
                    'vif_type': FLAGS.libvirt_vif_type,
                    'nics': nics,
                    'ebs_root': ebs_root,
                    'boot' : boot,
                    'local_device': local_device,
                    'volumes': block_device_mapping,
                    'use_virtio_for_bridges':
                            FLAGS.libvirt_use_virtio_for_bridges,
                    'ephemerals': ephemerals}

        root_device_name = driver.block_device_info_get_root(block_device_info)
        if root_device_name:
            xml_info['root_device'] = block_device.strip_dev(root_device_name)
            xml_info['root_device_name'] = root_device_name
        else:
            # NOTE(yamahata):
            # for nova.api.ec2.cloud.CloudController.get_metadata()
            xml_info['root_device'] = self.default_root_device
            db.instance_update(
                nova_context.get_admin_context(), instance['id'],
                {'root_device_name': '/dev/' + self.default_root_device})

        if local_device:
            db.instance_update(
                nova_context.get_admin_context(), instance['id'],
                {'default_local_device': '/dev/' + self.default_local_device})

        swap = driver.block_device_info_get_swap(block_device_info)
        if driver.swap_is_usable(swap):
            xml_info['swap_device'] = block_device.strip_dev(
                swap['device_name'])
        elif (inst_type['swap'] > 0 and
              not self._volume_in_mapping(self.default_swap_device,
                                          block_device_info)):
            xml_info['swap_device'] = self.default_swap_device
            db.instance_update(
                nova_context.get_admin_context(), instance['id'],
                {'default_swap_device': '/dev/' + self.default_swap_device})

        if instance.get('config_drive') or instance.get('config_drive_id'):
            xml_info['config_drive'] = xml_info['basepath'] + "/disk.config"

        if FLAGS.vnc_enabled and FLAGS.libvirt_type not in ('lxc', 'uml'):
            xml_info['vncserver_host'] = FLAGS.vncserver_host
            xml_info['vnc_keymap'] = FLAGS.vnc_keymap
        if not rescue:
            if instance['kernel_id']:
                xml_info['kernel'] = xml_info['basepath'] + "/kernel"

            if instance['ramdisk_id']:
                xml_info['ramdisk'] = xml_info['basepath'] + "/ramdisk"

            xml_info['disk'] = xml_info['basepath'] + "/disk"

        if image_info:
            xml_info['image_location'] = xml_info['basepath'] + "/image-" + str(image_info['id'] )
        return xml_info


    def to_xml(self, instance, network_info, rescue=False,
               block_device_info=None, image_info=None):
        # TODO(termie): cache?
        LOG.debug(_('instance %s: starting toXML method'), instance['name'])
        xml_info = self._prepare_xml_info(instance, network_info, rescue,
                                          block_device_info, image_info)
        xml = str(Template(self.libvirt_xml, searchList=[xml_info]))
        LOG.debug(_('instance %s: finished toXML method'), instance['name'])
        return xml

    def _create_image(self, context, inst, libvirt_xml, suffix='',
                      disk_images=None, network_info=None,
                      block_device_info=None, image_info=None):
        super(BootFromCDandVolumeLibvirtConnection, self)._create_image(context, inst, libvirt_xml, suffix, disk_images, network_info, block_device_info)
        if image_info:
            basepath = os.path.join(FLAGS.instances_path, inst['name'])
            path = basepath + "/image-" + str(image_info['id'])
            if not os.path.exists(path):
                images.fetch(context, image_info['id'], path, inst['user_id'], inst['project_id'] )

    @exception.wrap_exception()
    def spawn(self, context, instance, network_info,
              block_device_info=None, image_info=None):
        xml = self.to_xml(instance, network_info, False,
                          block_device_info=block_device_info,
                          image_info=image_info)
        self.firewall_driver.setup_basic_filtering(instance, network_info)
        self.firewall_driver.prepare_instance_filter(instance, network_info)
        self._create_image(context, instance, xml, network_info=network_info,
                           block_device_info=block_device_info, image_info=image_info)

        _domain = self._create_new_domain(xml)
        LOG.debug(_("instance %s: is running"), instance['name'])
        self.firewall_driver.apply_instance_filter(instance, network_info)

        def _wait_for_boot():
            """Called at an interval until the VM is running."""
            instance_name = instance['name']

            try:
                state = self.get_info(instance_name)['state']
            except exception.NotFound:
                msg = _("During reboot, %s disappeared.") % instance_name
                LOG.error(msg)
                raise utils.LoopingCallDone

            if state == power_state.RUNNING:
                msg = _("Instance %s spawned successfully.") % instance_name
                LOG.info(msg)
                raise utils.LoopingCallDone

        timer = utils.LoopingCall(_wait_for_boot)
        return timer.start(interval=0.5, now=True)

