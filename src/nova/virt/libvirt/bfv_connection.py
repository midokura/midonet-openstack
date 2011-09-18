# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
# All Rights Reserved.
# Copyright (c) 2010 Citrix Systems, Inc.
# Copyright (c) 2011 Piston Cloud Computing, Inc
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

import hashlib
import functools
import multiprocessing
import netaddr
import os
import random
import re
import shutil
import sys
import tempfile
import time
import uuid
from xml.dom import minidom
from xml.etree import ElementTree

from eventlet import greenthread
from eventlet import tpool

from nova import block_device
from nova import context as nova_context
from nova import db
from nova import exception
from nova import flags
import nova.image
from nova import log as logging
from nova import utils
from nova import vnc
from nova.auth import manager
from nova.compute import instance_types
from nova.compute import power_state
from nova.virt import disk
from nova.virt import driver
from nova.virt import images
from nova.virt.libvirt import netutils


libvirt = None
libxml2 = None
Template = None



LOG = logging.getLogger('nova.virt.libvirt_conn')


def get_connection(read_only=False):
    conn = nova.virt.libvirt.connection.get_connection(read_only)
    return BootFromCDandVolumeLibvirtConnection(read_only)



def _get_eph_disk(ephemeral):
    return 'disk.eph' + str(ephemeral['num'])



import nova.virt.libvirt.connection as libvirt_conn


FLAGS = flags.FLAGS


class BootFromCDandVolumeLibvirtConnection(libvirt_conn.LibvirtConnection):


    def __init__(self, read_only):
        print "--------derived class ----"
        super(BootFromCDandVolumeLibvirtConnection, self).__init__(read_only)


    def _check_image_type(self, image_ref, type):
        print "------------------nova_context---"
        print nova_context
        elevated = nova_context.get_admin_context()
        print "----------elevated -------------"
        print dir(elevated)
        print elevated
        (image_service, image_id) = nova.image.get_image_service(elevated, image_ref)
        image = image_service.show(elevated, image_id)
        return True if image['disk_format'] == type else False


    # intentionaly overriding private method to hack around.
    def _prepare_xml_info(self, instance, network_info, rescue,
                          block_device_info=None):
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

        if (instance['image_ref'] and
            self._check_image_type(instance['image_ref'], 'iso')):
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

        config_drive = False
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
        return xml_info


