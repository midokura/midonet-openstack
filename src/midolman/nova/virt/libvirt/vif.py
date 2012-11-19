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

from nova.openstack.common import log as logging
from nova.virt import vif

LOG = logging.getLogger(__name__)

class MidonetVifDriver(vif.VIFDriver):

    def __init__(self, **kwargs):
        pass

    def plug(self, instance, vif, **kwargs):
        pass

    def unplug(self, instance, vif, **kwargs):
        pass

