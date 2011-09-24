# Copyright (C) 2010 Midokura KK
#
# Configuration file helper for Midolman Net Agent.

import ConfigParser
from midolman import config as midolman_config

_SERVER_SECTION = 'server'
_MIDOLMAN_SECTION = 'midolman'
_OPENVSWITCH_SECTION = 'openvswitch'
_INTERFACE_SECTION = 'interface'

_SERVER_HOST = 'host'
_SERVER_PORT = 'port'
_MIDOLMAN_CONF = 'conf'
_OPENVSWITCH_BRIDGE_PREFIX = 'bridge_prefix'
_INTERFACE_MTU = 'mtu'
_OPENVSWITCH_CONTROLLER = 'controller'

_DEFAULT_VALUES = {
    _SERVER_HOST: '0.0.0.0',
    _SERVER_PORT: 8999,
    _MIDOLMAN_CONF: '/etc/midolman.conf',
    _OPENVSWITCH_BRIDGE_PREFIX: 'mbr',
    _OPENVSWITCH_CONTROLLER: 'unix:/var/run/openvswitch/db.sock',
    _INTERFACE_MTU: 1300  # Temporary hack
}


class AgentConfig(object):
    """Configuration class for Midolman net agent.
    """

    def __init__(self):
        """Initialize AgentConfig object.
        """
        self._parser = ConfigParser.SafeConfigParser(_DEFAULT_VALUES)
        self._midolman_conf_vals = None

    def read(self, conf_file):
        """Read and load a configuration file.

        Args:
            config_file: Net agent configuration file path.
        """
        self._parser.read([conf_file])

    @property
    def server_host(self):
        """Host that net agent server listens to.
        """
        return self._parser.get(_SERVER_SECTION, _SERVER_HOST)

    @property
    def server_port(self):
        """Port that net agent server listens to.
        """
        return self._parser.getint(_SERVER_SECTION, _SERVER_PORT)

    @property
    def midolman_conf(self):
        """Path to the Midolman configuration file.
        """
        return self._parser.get(_MIDOLMAN_SECTION, _MIDOLMAN_CONF)

    @property
    def midolman_conf_vals(self):
        """ConfVals object loaded from the Midolman configuration file.
        """
        if not self._midolman_conf_vals:
            self._midolman_conf_vals = midolman_config.get_conf_vals_from_file(
                self.midolman_conf)
        return self._midolman_conf_vals

    @property
    def openvswitch_bridge_prefix(self):
        """Prefix of Openvswitch bridge name.
        """
        return self._parser.get(_OPENVSWITCH_SECTION,
                                _OPENVSWITCH_BRIDGE_PREFIX)

    @property
    def openvswitch_controller(self):
        """Prefix of Openvswitch controller.
        """
        return self._parser.get(_OPENVSWITCH_SECTION,
                                _OPENVSWITCH_CONTROLLER)
        
    @property
    def interface_mtu(self):
        """MTU of the interface.
        """
        return self._parser.getint(_INTERFACE_SECTION,
                                   _INTERFACE_MTU)

Config = AgentConfig()

