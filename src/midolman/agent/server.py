# Copyright (C) 2011 Midokura KK
#
# Net Agent server

import json
import os
import random
import time
import SocketServer
import traceback

from midolman import tap
from midolman.agent.config import Config
from midolman.agent.openvswitch import OvsConn

_BUFFSIZE = 1024
_RET_CODE_SUCCESS = 0
_RET_CODE_ERROR = 1

def _get_random_bridge_name():
    """Get a random bridge name.

    Returns:
    A randomly generated bridge name.
    """
    return "%s%d" % (Config.openvswitch_bridge_prefix,
                     random.randint(1, 9999999999))

class NetAgent(object):
    """Sets up local network resources.
    """

    def create_port(self, data):
        """Add an OVS port and set port_id as its external ID.

        Args:
           port_id: Port ID to set as the external ID of the OVS port.
           name: Interface name to create.
           external_id: External ID for the device.
           uid: UID of the tap interface
           gid: GID of the tap interface
           mac_address: MAC of the tap interface

        Returns:
            The name of the interface created.
        """
        if not 'external_id' in data or not data['external_id']:
            raise ValueError("External ID is missing or invalid.")
        external_id = str(data['external_id'])

        if not 'name' in data or not data['name']:
            raise ValueError("Interface name is missing or invalid.")
        name = str(data['name'])

        if not 'port_id' in data or not data['port_id']:
            raise ValueError("Port ID is missing or invalid.")
        port_id = str(data['port_id'])
        tap_if = tap.create_persistent_tap_if(name,
                                              owner=data.get('uid'),
                                              group=data.get('gid'),
                                              mac=data.get('mac_address'))
        print "Tap created: %r" % tap_if

        ovs_conn = OvsConn.get_connection()
        ovs_bridges = ovs_conn.get_bridge_names_by_external_id(
                Config.midolman_conf_vals.ovs_ext_id_key, external_id)

        if ovs_bridges:
            bridge_name = ovs_bridges[0]
        else:
            bridge_name = _get_random_bridge_name()
            ext_ids = {Config.midolman_conf_vals.ovs_ext_id_key: external_id}
            res = ovs_conn.add_bridge(bridge_name,
                                      external_ids=ext_ids,
                                      fail_mode='secure')
            print "OVS bridge added: %r" % res
            time.sleep(1)

        ext_ids = {Config.midolman_conf_vals.ovs_ext_id_key: port_id}
        res = ovs_conn.add_system_port(bridge_name, tap_if,
                                       external_ids=ext_ids)
        print "OVS port added: %r" % res

        time.sleep(1)
        ovs_conn.close()
        tap.set_if_flags(tap_if, up=True, noarp=True, multicast=False)

        # HACK! Set the MTU to 1300.
        os.system("ip link set %s mtu %d" % (tap_if, Config.interface_mtu))
        return dict(ret_code=_RET_CODE_SUCCESS, name=tap_if)

    def delete_port(self, data):
        """ Delete an OVS port

        Args:
            data: Dictionary of inputs.  The dictionary should contain:
                'name': Interface name

        Returns:
            True if successful.
        """
        if not 'name' in data or not data['name']:
            raise ValueError("Interface name is missing or invalid.")
        name = str(data['name'])

        # OVS connection opened everytime because there were
        # errors when the connection was kept open.  Investigate.
        ovs_conn = OvsConn.get_connection()
        ovs_conn.del_port(name)
        time.sleep(1)
        ovs_conn.close()

        tap.destroy_persistent_tap_if(name)
        return dict(ret_code=_RET_CODE_SUCCESS)

    def delete_bridge(self, data):
        """Deletes OVS bridge.

        Args:
            data: Dictionary of inputs.  It should contain:
                name: Name of the bridge

        Returns:
            True if successful.
        """
        if not 'name' in data or not data['name']:
            raise ValueError("Bridge name is missing or invalid.")
        name = str(data['name'])

        ovs_conn = OvsConn.get_connection()
        ovs_conn.del_bridge(name)
        time.sleep(1)
        ovs_conn.close()
        return dict(ret_code=_RET_CODE_SUCCESS)


    def handle(self, data):
        """Handles the request data.  Dispatches to the right method.

        Args:
            data: Dictionary of inputs.  The dictionary should contain:
                'action': Name of the method to invoke
        """
        if not 'action' in data or not data['action']:
            raise ValueError("Action not specified.")

        action = data['action']
        return getattr(self, action)(data)


class NetAgentRequestHandler(SocketServer.BaseRequestHandler):

    def __init__(self, request, client_address, server):
        """Initialize NetAgentRequestHandler object.

        Args:
            request: TCP request object.
            client_address: Address that the request came from.
            server: Server for the request.
        """
        self._agent = NetAgent()
        SocketServer.BaseRequestHandler.__init__(self, request,
                                                 client_address,
                                                 server)

    def handle(self):
        """Handle the request.
        """
        data = self.request.recv(_BUFFSIZE).strip()

        deser_data = json.loads(data)
        try:
            result = self._agent.handle(deser_data)
        except Exception, ex:
            print ex
            traceback.print_stack()
            result = dict(ret_code=_RET_CODE_ERROR)
        self.request.send(json.dumps(result))


class NetAgentTCPServer(SocketServer.TCPServer):

    def __init__(self, server_address):
        """Initialize NetAgentTCPServer object.

        Args:
            server_address: Server IP address
        """
        SocketServer.TCPServer.__init__(self, server_address,
                                        NetAgentRequestHandler)

    def serve_forever(self):
        """Start the server.
        """
        # Initialize OVS
        OvsConn.initialize(Config.midolman_conf_vals.ovsdb_url,
                           Config.midolman_conf_vals.ovs_ext_id_key)

        SocketServer.TCPServer.serve_forever(self)

