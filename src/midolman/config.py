# Copyright (C) 2011 Midokura KK
import ConfigParser
import socket
import StringIO

from midolman import ieee_802

# Section constants
_BRIDGE_SECTION = 'bridge'
_MC_SECTION = 'memcache'
_OPFL_SECTION = 'openflow'
_OVS_SECTION = 'openvswitch'
_VRN_SECTION = 'vrn'
_ZK_SECTION = 'zookeeper'

# Option constants
# TODO(pino): move the ip address attribute out of this section
_BRIDGE_MAC_EXPIRE = 'mac_port_mapping_expire'
_MC_HOSTS = 'memcache_hosts'
_OPFL_EXPIRE = 'flow_expire'
_OPFL_IDLE = 'flow_idle_expire'
_OPFL_IP_ADDR = 'public_ip_address'
_OPFL_USE_WILDCARDS = 'use_flow_wildcards'
_OVS_DB_URL = 'openvswitchdb_url'
_OVS_EXT_ID_KEY = 'midolman_ext_id_key'
_OVS_PORT_SERVICE_EXT_ID_KEY = 'midolman_port_service_ext_id_key'
_OVS_PORT_ID_EXT_ID_KEY = 'midolman_port_id_ext_id_key'
_VRN_FLOW_PORT = 'flow_port'
_VRN_INVAL_PORT = 'inval_port'
_ROUTER_NETWORK_ID = 'router_network_id'
_ZK_HOSTS = 'zookeeper_hosts'
_ZK_ROOT = 'midolman_root'
_ZK_TIMEOUT = 'zookeeper_timeout'

# These are not option names; they are used to build directory paths.
_ZK_BRIDGE_SUFFIX = 'bridges'
_ZK_MAC_PORT_MAP_SUFFIX = 'mac_port_dicts'
_ZK_PORT_LOC_MAP_SUFFIX = 'port_location_dicts'
_ZK_PORT_SUFFIX = 'ports'
_ZK_ROUTER_SUFFIX = 'routers'
_ZK_ROUTING_TABLE_SUFFIX = 'routing_tables'
_ZK_VRN_SUFFIX = 'vrns'

_DEFAULT_VALUES = {
    _BRIDGE_MAC_EXPIRE: \
        ieee_802.MemcachedDynamicFilteringDatabase.DEFAULT_CACHE_TIMEOUT,
    _MC_HOSTS: '127.0.0.1:11211',
    _OPFL_EXPIRE: '15',
    _OPFL_IDLE: '3',
    _OPFL_IP_ADDR: '127.0.0.1',
    _OPFL_USE_WILDCARDS: 'False',
    _OVS_DB_URL: 'unix:/var/run/openvswitch/db.sock',
    _OVS_EXT_ID_KEY: 'midolman-vnet',
    _OVS_PORT_SERVICE_EXT_ID_KEY: 'midolman_port_service',
    _OVS_PORT_ID_EXT_ID_KEY: 'midolman_port_id',
    _VRN_FLOW_PORT: '6672',
    _VRN_INVAL_PORT: '6673',
    _ROUTER_NETWORK_ID: '00000000-0000-0000-0000-000000000000',
    _ZK_HOSTS: '127.0.0.1:2181',
    _ZK_ROOT: '/midolman',
    _ZK_TIMEOUT: '10000',
}

class ConfVals(object):
    """Midolman's configuration, usually parsed from stanza file(s).
    """
    config_parser = None

    def __init__(self, config_parser):
        """Initialize ConfVals object.

        Args:
           config_parser: ConfigParser object.
        """
        self._config_parser = config_parser

    @property
    def flow_expire(self):
        """Gets openflow section's flow_expire option value.
        """
        return self._config_parser.getint(_OPFL_SECTION, _OPFL_EXPIRE)

    @property
    def flow_expire_min(self):
        """Gets openflow's minimun flow expiration value.
        """
        flow_expire = self.flow_expire
        return int(round(flow_expire - flow_expire*0.1))

    @property
    def flow_expire_max(self):
        """Gets openflow's maximum expiration value.
        """
        flow_expire = self.flow_expire
        return int(round(flow_expire + flow_expire*0.1))

    @property
    def flow_idle_expire(self):
        """Gets openflow section's flow_idle_expire option value.
        """
        return self._config_parser.getint(_OPFL_SECTION, _OPFL_IDLE)

    @property
    def public_ip_string(self):
        """Gets openflow section's public_ip_address option value.
        """
        return self._config_parser.get(_OPFL_SECTION, _OPFL_IP_ADDR)

    @property
    def public_ip_binary(self):
        """Gets openflow section's public_ip_binary option value.
        """
        return socket.inet_pton(socket.AF_INET, self.public_ip_string)

    @property
    def use_flow_wildcards(self):
        """Gets openflow section's use_flow_wildcards value.
        """
        return self._config_parser.getboolean(_OPFL_SECTION,
                                              _OPFL_USE_WILDCARDS)

    @property
    def memcache_host_list(self):
        """Gets memcache section's host_list opton value as a list of hosts.
        """
        return self._config_parser.get(_MC_SECTION, _MC_HOSTS).split(',')

    @property
    def mac_port_timeout(self):
        """Gets bridge section's mac_port_mapping_expire option value.
        """
        return self._config_parser.getint(_BRIDGE_SECTION, _BRIDGE_MAC_EXPIRE)

    @property
    def zk_hosts(self):
        """Gets zookeeper sections' zookeeper_hosts option value.
        """
        return self._config_parser.get(_ZK_SECTION, _ZK_HOSTS)

    @property
    def zk_timeout(self):
        """Gets zookeeper sections' zookeeper_timeout option value.
        """
        return self._config_parser.getint(_ZK_SECTION, _ZK_TIMEOUT)

    @property
    def zk_root(self):
        """Gets zookeeper section's midolman_root option value.
        """
        return self._config_parser.get(_ZK_SECTION, _ZK_ROOT)

    @property
    def zk_bridge_root(self):
        """Gets zookeeper section's bridges option value.
        """
        return '/'.join([self.zk_root, _ZK_BRIDGE_SUFFIX])

    @property
    def zk_port_root(self):
        """Gets zookeeper section's ports option value.
        """
        return '/'.join([self.zk_root, _ZK_PORT_SUFFIX])

    @property
    def zk_router_root(self):
        """Gets zookeeper section's routers opton value.
        """
        return '/'.join([self.zk_root, _ZK_ROUTER_SUFFIX])

    @property
    def zk_vrn_root(self):
        """Gets zookeeper section's vrns option value.
        """
        return '/'.join([self.zk_root, _ZK_VRN_SUFFIX])

    @property
    def zk_port_loc_map_root(self):
        """Gets zookeeper section's port_location_dicts option value.
        """
        return '/'.join([self.zk_root, _ZK_PORT_LOC_MAP_SUFFIX])

    @property
    def zk_routing_table_root(self):
        """Gets zookeeper section's routing_tables option value.
        """
        return '/'.join([self.zk_root, _ZK_ROUTING_TABLE_SUFFIX])

    @property
    def zk_mac_port_map_root(self):
        """Gets zookeeper section's mac_port_dicts option value.
        """
        return '/'.join([self.zk_root, _ZK_MAC_PORT_MAP_SUFFIX])

    @property
    def ovsdb_url(self):
        """Gets openvswitch section's openvswitchdb_url option value.
        """
        return self._config_parser.get(_OVS_SECTION, _OVS_DB_URL)

    @property
    def ovs_ext_id_key(self):
        """Gets openvswitch section's midolman_ext_id_key option value.
        """
        return self._config_parser.get(_OVS_SECTION, _OVS_EXT_ID_KEY)

    @property
    def ovs_port_service_ext_id_key(self):
        """Gets openvswitch section's midolman_port_service_ext_id_key
        option value.
        """
        return self._config_parser.get(_OVS_SECTION,
                                       _OVS_PORT_SERVICE_EXT_ID_KEY)

    @property
    def ovs_port_id_ext_id_key(self):
        """Gets openvswitch section's midolman_port_id_ext_id_key option
        value.
        """
        return self._config_parser.get(_OVS_SECTION, _OVS_PORT_ID_EXT_ID_KEY)

    @property
    def flow_port(self):
        """Gets vrn sections' flow_port option value.
        """
        return self._config_parser.getint(_VRN_SECTION, _VRN_FLOW_PORT)

    @property
    def inval_port(self):
        """Gets vrn sections' inval_port option value.
        """
        return self._config_parser.getint(_VRN_SECTION, _VRN_INVAL_PORT)

    @property
    def router_network_id(self):
        """Gets router network ID of the system. 
        """
        return self._config_parser.get(_VRN_SECTION, _ROUTER_NETWORK_ID)


def get_conf_vals_from_files(files):
    """Get ConfVal object from a list of files.

    Args:
        files: Config files to load.

    Returns:
        ConfVals object.
    """
    config_parser = ConfigParser.SafeConfigParser(_DEFAULT_VALUES)
    config_parser.read(files)
    return ConfVals(config_parser)

def get_conf_vals_from_file(file):
    """Get ConfVal object from a file.

    Args:
       file: Config file to load from.

    Returns:
       ConfVals object.
    """
    return get_conf_vals_from_files([file])

def get_conf_vals_from_string(config_str):
    """Returns ConfVals object constructed from a string passed in.

    Args:
        config_str: string read by ConfigParser.

    Returns:
        ConfVals object.
    """
    conf_stream = StringIO.StringIO(config_str)

    config_parser = ConfigParser.SafeConfigParser(_DEFAULT_VALUES)
    config_parser.readfp(conf_stream)

    conf_stream.close()
    return ConfVals(config_parser)


def get_default_values():
    """Returns the default values used for the config as a dictionary.

    Returns:
        A dictionary of default values used in parsing the configuration file.
    """
    return _DEFAULT_VALUES
