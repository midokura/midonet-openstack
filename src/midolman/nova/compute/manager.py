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


from nova import exception
from nova import flags
import nova.image
from nova import log as logging
from nova import utils
from nova.compute import task_states
from nova.compute import vm_states
from nova.notifier import api as notifier
from nova.compute.manager import ComputeManager

LOG = logging.getLogger('midolman.nova.compute.manager')
FLAGS = flags.FLAGS

def publisher_id(host=None):
    return notifier.publisher_id("compute", host)

class MidoComputeManager(ComputeManager):

    def _run_instance(self, context, instance_id, **kwargs):
        """Launch a new instance with specified options."""
        def _check_image_size():
            """Ensure image is smaller than the maximum size allowed by the
            instance_type.

            The image stored in Glance is potentially compressed, so we use two
            checks to ensure that the size isn't exceeded:

                1) This one - checks compressed size, this a quick check to
                   eliminate any images which are obviously too large

                2) Check uncompressed size in nova.virt.xenapi.vm_utils. This
                   is a slower check since it requires uncompressing the entire
                   image, but is accurate because it reflects the image's
                   actual size.


            To implement boot from CD-ROM in the MidoStack version, this method 
            returns the image data retrieved from the image server.
            """
            # NOTE(jk0): image_ref is defined in the DB model, image_href is
            # used by the image service. This should be refactored to be
            # consistent.
            image_href = instance['image_ref']
            image_service, image_id = nova.image.get_image_service(context,
                                                                   image_href)
            image_meta = image_service.show(context, image_id)

            try:
                size_bytes = image_meta['size']
            except KeyError:
                # Size is not a required field in the image service (yet), so
                # we are unable to rely on it being there even though it's in
                # glance.

                # TODO(jk0): Should size be required in the image service?
                return image_meta

            instance_type_id = instance['instance_type_id']
            instance_type = self.db.instance_type_get(context,
                    instance_type_id)
            allowed_size_gb = instance_type['local_gb']

            # NOTE(jk0): Since libvirt uses local_gb as a secondary drive, we
            # need to handle potential situations where local_gb is 0. This is
            # the default for m1.tiny.
            if allowed_size_gb == 0:
                return image_meta

            allowed_size_bytes = allowed_size_gb * 1024 * 1024 * 1024

            LOG.debug(_("image_id=%(image_id)d, image_size_bytes="
                        "%(size_bytes)d, allowed_size_bytes="
                        "%(allowed_size_bytes)d") % locals())

            if size_bytes > allowed_size_bytes:
                LOG.info(_("Image '%(image_id)d' size %(size_bytes)d exceeded"
                           " instance_type allowed size "
                           "%(allowed_size_bytes)d")
                           % locals())
                raise exception.ImageTooLarge()

            return image_meta

        context = context.elevated()
        instance = self.db.instance_get(context, instance_id)

        requested_networks = kwargs.get('requested_networks', None)

        if instance['name'] in self.driver.list_instances():
            raise exception.Error(_("Instance has already been created"))

        image_info = _check_image_size()

        LOG.audit(_("instance %s: starting..."), instance_id,
                  context=context)
        updates = {}
        updates['host'] = self.host
        updates['launched_on'] = self.host
        updates['vm_state'] = vm_states.BUILDING
        updates['task_state'] = task_states.NETWORKING
        instance = self.db.instance_update(context, instance_id, updates)
        instance['injected_files'] = kwargs.get('injected_files', [])
        instance['admin_pass'] = kwargs.get('admin_password', None)

        is_vpn = instance['image_ref'] == str(FLAGS.vpn_image_id)
        try:
            # NOTE(vish): This could be a cast because we don't do anything
            #             with the address currently, but I'm leaving it as
            #             a call to ensure that network setup completes.  We
            #             will eventually also need to save the address here.
            if not FLAGS.stub_network:
                network_info = self.network_api.allocate_for_instance(context,
                                    instance, vpn=is_vpn,
                                    requested_networks=requested_networks)
                LOG.debug(_("instance network_info: |%s|"), network_info)
            else:
                # TODO(tr3buchet) not really sure how this should be handled.
                # virt requires network_info to be passed in but stub_network
                # is enabled. Setting to [] for now will cause virt to skip
                # all vif creation and network injection, maybe this is correct
                network_info = []

            self._instance_update(context,
                                  instance_id,
                                  vm_state=vm_states.BUILDING,
                                  task_state=task_states.BLOCK_DEVICE_MAPPING)

            (swap, ephemerals,
             block_device_mapping) = self._setup_block_device_mapping(
                context, instance_id)
            block_device_info = {
                'root_device_name': instance['root_device_name'],
                'swap': swap,
                'ephemerals': ephemerals,
                'block_device_mapping': block_device_mapping}

            self._instance_update(context,
                                  instance_id,
                                  vm_state=vm_states.BUILDING,
                                  task_state=task_states.SPAWNING)

            # TODO(vish) check to make sure the availability zone matches
            try:
                self.driver.spawn(context, instance,
                                  network_info, block_device_info, image_info)
            except Exception as ex:  # pylint: disable=W0702
                msg = _("Instance '%(instance_id)s' failed to spawn. Is "
                        "virtualization enabled in the BIOS? Details: "
                        "%(ex)s") % locals()
                LOG.exception(msg)
                return

            current_power_state = self._get_power_state(context, instance)
            self._instance_update(context,
                                  instance_id,
                                  power_state=current_power_state,
                                  vm_state=vm_states.ACTIVE,
                                  task_state=None,
                                  launched_at=utils.utcnow())

            usage_info = utils.usage_from_instance(instance)
            notifier.notify('compute.%s' % self.host,
                            'compute.instance.create',
                            notifier.INFO, usage_info)

        except exception.InstanceNotFound:
            # FIXME(wwolf): We are just ignoring InstanceNotFound
            # exceptions here in case the instance was immediately
            # deleted before it actually got created.  This should
            # be fixed once we have no-db-messaging
            pass

    # Override run_instance so that we can pass 'image_info' dictionary to virt.
    @exception.wrap_exception(notifier=notifier, publisher_id=publisher_id())
    def run_instance(self, context, instance_id, **kwargs):
        self._run_instance(context, instance_id, **kwargs)


