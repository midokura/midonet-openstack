# Copyright (C) 2010 Midokura KK
# Author: Romain Lenglet (romain.lenglet@berabera.info)

# A pure Python implementation of the Open vSwitch database protocol
# used to configure bridges, ports, etc.
#
# This module can connect to the ovsdb daemon using a Unix domain
# server socket, using a 'unix:...' URL.  Other connection schemes
# (TCP, etc.) are not supported.

import json
import logging
import os
import socket
import sys  #XXX
import uuid

import ovs
from ovs.jsonrpc import Message

def _generate_uuid():
  """Generate a random UUID string.

  Returns:
    A new random UUID as a string.
  """
  return str(uuid.uuid4())


def _get_uuid_name_from_uuid(uuid):
  """Get a UUID name from a UUID string.

  Args:
    uuid: The UUID string to convert.

  Returns:
    A string containing the UUID name for the UUID, as a string.
  """
  return 'row%s' % uuid.replace('-', '_')


def _substitute_uuids(json_val, substs_uuids):
  """Replace all ['uuid', uuid] JSON-encodable values by UUID names.

  Args:
    json_val: The JSON-encodable value to transform.
    substs_uuids: The list of UUIDs to substitute. No other UUIDs are
        subsitituted.

  Returns:
    A JSON-encodable value with the ['uuid', uuid] values substituted.
  """
  if type(json_val) is list:
    if (len(json_val) == 2 and json_val[0] == 'uuid'
        and json_val[1] in substs_uuids):
      return ['named-uuid', _get_uuid_name_from_uuid(json_val[1])]
    else:
      return [_substitute_uuids(v, substs_uuids) for v in json_val]
  elif type(json_val) is dict:
    return dict((k, _substitute_uuids(v, substs_uuids))
                for k, v in json_val.iteritems())
  else:
    return json_val


def _uuid_list_append(json_uuid_list, uuid):
  """Append an UUID into a JSON-encodable list of UUIDs.

  Args:
    json_uuid_list: A JSON-encodable list of UUIDs.
    uuid: The UUID to append.

  Returns:
    The new JSON-encodable list with the UUID appended.
  """
  if json_uuid_list == []:  # empty list
    return ['uuid', uuid]
  elif json_uuid_list[0] == 'uuid':  # single element
    return [json_uuid_list, ['uuid', uuid]]
  else:
    json_uuid_list.append(['uuid', uuid])
    return json_uuid_list


def _bridge_id_where_clause(bridge_id):
  """Create a where clause to select a bridge given its identifier.

  Args:
    bridge_id: If a string, the name of the bridge.  If an integer,
        the datapath identifier of the bridge.

  Returns:
    A where clause to select the bridge, suitable for including in a
    clause list to pass to Transaction.select().
  """
  if isinstance(bridge_id, (int, long)):
    return ['datapath_id', '==', '%016x' % bridge_id]
  else:
    return ['name', '==', bridge_id]


def _where_uuid_equals(uuid):
  """Get a JSON-encodable 'where' clause to match the row with the uuid.

  Args:
    uuid: The UUID string of the row to match with the returned 'where'
        clause.

  Returns:
    A JSON-encodable value that represents a 'where' clause matching rows
    with the given UUID.
  """
  return [['_uuid', '==', ['uuid', uuid]]]


class ServerConnection(object):
  """A connection to an Open vSwitch database server.
  """

  def __init__(self, database, conn):
    """Initialize a connection to the Open vSwitch DB over the socket.
    This should not be called directly.  Instead, use
    ServerConnectionFactory.open_ovsdb_connection().

    Args:
      database: The name of the database.
      conn: The socket onto which to initialize the connection.
    """
    self._database = database
    self._conn = conn
    # A counter used to allocate an unique ID to each operation.
    self._op_id = 0

  def close(self):
    """Close the socket connection to the Open vSwitch DB server.
    """
    self._conn.close()

  def _allocate_new_operation_id(self):
    """Get a new unique operation id.

    Returns:
      A unique operation id.
    """
    id = self._op_id
    self._op_id += 1
    return id

  def _do_json_rpc(self, op):
    """Apply a operation to the database.

    Args:
      op: The Operation object to apply.

    Returns:
      True if the Operation was successfully applied, False otherwise.
    """
    id = self._allocate_new_operation_id()
    request = Message.from_json(op.create_jsonrpc_request(id))

    s = request.is_valid()
    if s:
      raise ValueError("not a valid JSON-RPC request: %s" % s)

    error = self._conn.send(request)
    reply = None
    while not error:
      error, reply = self._conn.recv_block()
      if reply:
        if reply.type == Message.T_REPLY and reply.id == id:
          break
        elif reply.type == Message.T_REQUEST and reply.method == "echo":
          logging.debug('openvswitch.py: sending an echo reply')
          self._conn.send(Message.create_reply(reply.params, reply.id))
        else:
          logging.debug('openvswitch.py: unrecognized server reply')
    if error:
      raise Exception("could not transact request: %s" % os.strerror(error))

    result = reply.to_json()
    if result['id'] is not id:
      raise Exception('wrong id in JSON-RPC result: %s' % result['id'])
    if result['error'] is not None:
      raise Exception('JSON-RPC remote error: %s' % result['error'])
    return result['result']

  def _select(self, table, where, columns):
    """Select data from the database.

    Args:
      table: The name of the table containing the rows to select.
      where: The JSON-encodable 'where' clause to be matched by the rows.
      columns: The list of columns to return.

    Returns:
      The list of selected rows.
    """
    tx = Transaction(self._database)
    tx.select(table, where, columns)
    return self._do_json_rpc(tx)[0]['rows']

  @classmethod
  def _ovs_map_to_dict(cls, ovs_map):
    """Converts an Open vSwitch DB map into a dict.

    Args:
      ovs_map: The Open vSwitch DB map to convert.

    Returns:
      A dict with the key-value pairs of the map.
    """
    if ovs_map is []:
      return {}
    elif ovs_map[0] == 'map':
      return dict(ovs_map[1])
    else:
      return {ovs_map[0]: ovs_map[1]}

  @classmethod
  def _dict_to_ovs_map(cls, d):
    """Converts an Open vSwitch DB map into a dict.

    Args:
      d: The dict to convert.

    Returns:
      An Open vSwitch DB map with the key-value pairs of the dict.
    """
    return ['map',  [[k, v] for k, v in d.iteritems()]]

  def add_bridge(self, name, external_ids={}, fail_mode=None):
    """Add a new bridge with the given name.

    Args:
      name: The name of the bridge to add.
      external_ids: A dict of arbitrary key-value string pairs to
          associate with the added bridge.
      fail_mode: The mode of the switch when set to connect to one or
          more controllers and none of of the controllers can be
          contacted. Either 'standalone', 'secure', or None
          (implementation-specific). Defaults to None.
    """
    tx = Transaction(self._database)

    if_uuid = _generate_uuid()
    tx.insert('Interface', if_uuid, {'name': name})
    port_uuid = _generate_uuid()
    tx.insert('Port', port_uuid, {'name': name,
                                  'interfaces': ['uuid', if_uuid]})
    bridge_uuid = _generate_uuid()
    datapath_type = ''
    # TODO(romain): Add an arg to set datapath_type = 'netdev' to use
    # the user-space datapath implementation for debugging instead of
    # the default kernel-space datapath implementation.
    bridge = {'name': name,
              'datapath_type': datapath_type,
              'ports': ['uuid', port_uuid],
              'external_ids': self._dict_to_ovs_map(external_ids),
              }
    if fail_mode is not None:
      bridge['fail_mode'] = fail_mode

    tx.insert('Bridge', bridge_uuid, bridge)

    # The 'Open_vSwitch' table should contain only one row, so pass
    # None as the UUID to update all the rows in there.  Insert the
    # bridge UUID into the set of activated bridges:
    tx.set_insert('Open_vSwitch', None, 'bridges', ['uuid', bridge_uuid])

    # Trigger ovswitchd to reload the configuration:
    tx.increment('Open_vSwitch', None, ['next_cfg'])

    if external_ids:
      external_ids_str = ', '.join(['%s=%s' % ext_id
                                    for ext_id in external_ids.iteritems()])
      tx.add_comment('added bridge %s with external ids %s' %
                     (name, external_ids_str))
    else:
      tx.add_comment('added bridge %s' % (name,))

    return self._do_json_rpc(tx)

  def add_system_port(self, bridge_id, port_name, external_ids={}, if_mac=''):
    """Create a port and a system interface, and add the port to a bridge.

    A system interface is for instance a physical Ethernet interface.

    Args:
      bridge_id: The identifier of the bridge to add the port to.
      port_name: The name of the port and of the interface to create.
      external_ids: A dict of arbitrary key-value string pairs to
          associate with the added port.
      if_mac: The MAC address of the underlying interface. If ''
          (default), a MAC address is determined by the bridge.
    """
    return self._add_port(bridge_id, port_name, if_type="system",
                          external_ids=external_ids, if_mac=if_mac)

  def add_internal_port(self, bridge_id, port_name, external_ids={},
                        if_mac=''):
    """Create a port and an internal interface, and add the port to a bridge.

    An internal interface is a virtual physical Ethernet interface
    usable to exchange packets only with the bridge.

    Args:
      bridge_id: The identifier of the bridge to add the port to.
      port_name: The name of the port and of the interface to create.
      external_ids: A dict of arbitrary key-value string pairs to
          associate with the added port.
      if_mac: The MAC address of the underlying interface. If ''
          (default), a MAC address is determined by the bridge.
    """
    return self._add_port(bridge_id, port_name, if_type="internal",
                          external_ids=external_ids, if_mac=if_mac)

  def add_tap_port(self, bridge_id, port_name, external_ids={}, if_mac=''):
    """Create a port and a TAP interface, and add the port to a bridge.

    Args:
      bridge_id: The identifier of the bridge to add the port to.
      port_name: The name of the port and of the TAP interface to create.
      external_ids: A dict of arbitrary key-value string pairs to
          associate with the added port.
      if_mac: The MAC address of the underlying interface. If ''
          (default), a MAC address is determined by the bridge.
    """
    return self._add_port(bridge_id, port_name, if_type='tap',
                          external_ids=external_ids, if_mac=if_mac)

  def add_gre_port(self, bridge_id, port_name, remote_ip, external_ids={},
                   if_mac='', local_ip=None,
                   out_key=None, in_key=None, key=None, tos=None,
                   ttl=None, csum=None, pmtud=None,
                   header_cache=None):
    """Create a port and a GRE interface, and add the port to a bridge.

    Args:
      bridge_id: The identifier of the bridge to add the port to.
      port_name: The name of the port and of the GRE interface to create.
      remote_ip: The tunnel remote endpoint's IP address.
      external_ids: A dict of arbitrary key-value string pairs to
          associate with the added port.
      if_mac: The MAC address of the underlying interface. If ''
          (default), a MAC address is determined by the bridge.
      local_ip: The tunnel local endpoint's IP address, or None if any
          IP address of the local host can be used.
      out_key: The GRE key to be set on outgoing packets.  If 'flow',
          the key may be set using the set_tunnel Nicira OpenFlow
          vendor extension.  If None, no GRE key is to be set.
      in_key: The GRE key that received packets must contain.  If
          'flow', any key will be accepted and the key will be placed
          in the tun_id field for matching in the flow table.  If None
          or 0, no key is required.
      key: Shorthand to set in_key and out_key at the same time.  If
          not None, overrides both out_key and in_key.
      tos: The value of the ToS bits to be set on the encapsulating
          packet.  If 'inherit', the ToS will be copied from the inner
          packet if it is IPv4 or IPv6.
      ttl: The TTL to be set on the encapsulating packet.  If
          'inherit', the TTL is copied from the inner packet if it is
          IPv4 or IPv6.  If None, the system's default TTL is used.
      csum: Compute GRE checksums on outgoing packets.  False by default.
      pmtud: Enable tunnel path MTU discovery.  True by default.
      header_cache: Enable caching of tunnel headers and the output
          path.  True by default.
    """
    if_options = {'remote_ip': remote_ip}
    if local_ip is not None:
      if_options['local_ip'] = local_ip
    if key is not None:
      if_options['key'] = str(key)
    else:
      if out_key is not None:
        if_options['out_key'] = str(out_key)
      if in_key is not None:
        if_options['in_key'] = str(in_key)
    if tos is not None:
      if_options['tos'] = str(tos)
    if ttl is not None:
      if_options['ttl'] = str(ttl)
    if csum is True:
      if_options['csum'] = 'true'
    if pmtud is False:
      if_options['pmtud'] = 'false'
    if header_cache is False:
      if_options['header_cache'] = 'false'

    return self._add_port(bridge_id, port_name, if_type='gre',
                          external_ids=external_ids, if_mac=if_mac,
                          if_options=if_options)

  def _add_port(self, bridge_id, port_name, if_type='', external_ids={},
                if_mac='', if_options={}):
    """Create a port and an interface, and add the port to a bridge.

    Args:
      bridge_id: The identifier of the bridge to add the port to.
      port_name: The name of the port and of the interface to create.
      if_type: The type of the interface. If '' (default), a normal interface is
          created. If 'gre', a GRE tunnel is created.
      external_ids: A dict of arbitrary key-value string pairs to
          associate with the added port.
      if_mac: The MAC address of the underlying interface. If ''
          (default), a MAC address is determined by the bridge.
      if_options: The options of the created interface, as a dict.
    """
    # TODO(romain): Support rate limiting, etc.
    tx = Transaction(self._database)

    # Do nothing if a port with that name already exists.
    port_rows = self._select('Port', [['name', '==', port_name]],
                             ['_uuid', 'interfaces'])
    if len(port_rows) > 0:
      # TODO(pino): check if the interface has the correct type, and if so
      # return True. Otherwise, remove the port and add it again or raise an
     # exception.
      return False

    # Find the bridge with that id.
    bridge_rows = self._select('Bridge', [_bridge_id_where_clause(bridge_id)],
                               ['_uuid'])
    if len(bridge_rows) != 1:
      raise Exception('no bridge with id %s' % bridge_id)
    bridge_uuid = bridge_rows[0]['_uuid'][1]

    # Create the port and its single interface.
    if_uuid = _generate_uuid()
    if_options = self._dict_to_ovs_map(if_options)
    tx.insert('Interface', if_uuid, {'name': port_name,
                                     'type': if_type,
                                     'mac': if_mac,
                                     'options': if_options})
    port_uuid = _generate_uuid()
    tx.insert('Port', port_uuid,
              {'name': port_name,
               'mac': if_mac,
               'interfaces': ['uuid', if_uuid],
               'external_ids': self._dict_to_ovs_map(external_ids)})
    # TODO(romain): Support options to set rate limits, etc. by
    # setting values of columns of the Port row.

    # Add the port to the bridge.
    tx.set_insert('Bridge', bridge_uuid, 'ports', ['uuid', port_uuid])

    if external_ids:
      external_ids_str = ', '.join(['%s=%s' % ext_id
                                    for ext_id in external_ids.iteritems()])
      tx.add_comment('added port %s to bridge %s with external ids %s' %
                     (port_name, bridge_id, external_ids_str))
    else:
      tx.add_comment('added port %s to bridge %s' %
                     (port_name, bridge_id))

    # Trigger ovswitchd to reload the configuration.
    tx.increment('Open_vSwitch', None, ['next_cfg'])

    return self._do_json_rpc(tx)

  def del_port(self, port_name):
    # TODO: doc
    tx = Transaction(self._database)

    # Delete all ports with that name.
    port_rows = self._select('Port', [['name', '==', port_name]],
                             ['_uuid', 'interfaces'])

    for port_row in port_rows:
      port_uuid = port_row['_uuid'][1]
      tx.delete('Port', port_uuid)
      ifs = port_row['interfaces']
      # TODO: Write an UUID set iterator to do that iteration here and
      # in del_bridge.
      if ifs[0] == 'uuid':
        ifs = [ifs]
      elif ifs[0] == 'set':
        ifs = ifs[1]
      for if_uuid in ifs:
        tx.delete('Interface', if_uuid[1])
      # Remove the port from all bridges.
      tx.set_delete('Bridge', None, 'ports', ['uuid', port_uuid])

    tx.add_comment('deleted port %s' % (port_name,))

    # Trigger ovswitchd to reload the configuration.
    tx.increment('Open_vSwitch', None, ['next_cfg'])

    return self._do_json_rpc(tx)

  def add_bridge_openflow_controller(
      self, bridge_id, target, connection_mode=None, max_backoff=None,
      inactivity_probe=None, controller_rate_limit=None,
      controller_burst_limit=None, discover_accept_regex=None,
      discover_update_resolv_conf=None, local_ip=None,
      local_netmask=None, local_gateway=None, external_ids={}):
    """Add an OpenFlow controller for a bridge.

    An OpenFlow controller target may be in any of the following forms
    for a primary controller (i.e. a normal OpenFlow controller):
      'ssl:$(ip)[:$(port)s]': The specified SSL port (default: 6633)
          on the host at the given ip, which must be expressed as an
          IP address (not a DNS name).
      'tcp:$(ip)[:$(port)s]': The specified TCP port (default: 6633)
          on the host at the given ip, which must be expressed as an
          IP address (not a DNS name).
      'discover': The switch discovers the controller by broadcasting
          DHCP requests with vendor class identifier 'OpenFlow'.

    An OpenFlow controller target may be in any of the following forms
    for a service controller (i.e. a controller that only connects
    temporarily and doesn't affect the datapath's fail_mode):
      'pssl:$(ip)[:$(port)s]': The specified SSL port (default: 6633)
          and ip Open vSwitch listens on for connections from
          controllers; the given ip must be expressed as an IP address
          (not a DNS name).
      'ptcp:$(ip)[:$(port)s]': The specified TCP port (default: 6633)
          and ip Open vSwitch listens on for connections from
          controllers; the given ip must be expressed as an IP address
          (not a DNS name).

    Args:
      bridge_id: The identifier of the bridge to udpate.
      target: The target to connect to the OpenFlow controller.
      connection_mode: Specifies how the controller is contacted over
          the network.  Either 'in-band', 'out-of-band', or None for
          the implementation-specific default.  Defaults to None.
      max_backoff: Maximum number of milliseconds to wait between
          connection attempts.  If None (default), the number is
          implementation-specific.
      inactivity_probe: Maximum number of milliseconds of idle time on
          connection to controller before sending an inactivity probe
          message.  If None (default), the number is
          implementation-specific.
      controller_rate_limit: The maximum rate at which packets in
          unknown flows will be forwarded to the OpenFlow controller,
          in packets per second.  If None (default), the rate is
          implementation-specific.
      controller_burst_limit: In conjunction with
          controller_rate_limit, the maximum number of unused packet
          credits that the bridge will allow to accumulate, in
          packets.  If None (default), the number is
          implementation-specific.
      discover_accept_regex: If the target is 'discover', a POSIX
          extended regular expression against which the discovered
          controller location is validated.  If None (default), the
          regex is implementation-specific.
      discover_update_resolv_conf: If the target is 'discover',
          specifies whether to update /etc/resolv.conf when the
          controller is discovered.  Must be True, False, or None.  If
          None (default), this setting is implementation-specific.
      local_ip: The IP address to configure on the local port to
          connect to the controller.  This can be set only when the
          connection_mode is 'in-band' and the target is 'discover'.
          In this case, if set to None (default), DHCP will be used to
          autoconfigure the local port.
      local_netmask: If local_ip is set, the IP netmask to configure
          on the local port.  Defaults to None.
      local_gateway: If local_ip is set, the IP address of the gateway
          to configure on the local port.
      external_ids: A dict of arbitrary key-value string pairs to
          associate with the added controller.
    """
    tx = Transaction(self._database)

    # Insert a new row into the 'Controller' table.
    controller = {'target': target,
                  'external_ids': self._dict_to_ovs_map(external_ids)}
    if connection_mode is not None:
      controller['connection_mode'] = connection_mode
    if max_backoff is not None:
      controller['max_backoff'] = str(max_backoff)
    if inactivity_probe is not None:
      controller['inactivity_probe'] = str(inactivity_probe)
    if controller_rate_limit is not None:
      controller['controller_rate_limit'] = str(controller_rate_limit)
    if controller_burst_limit is not None:
      controller['controller_burst_limit'] = str(controller_burst_limit)
    if discover_accept_regex is not None:
      controller['discover_accept_regex'] = discover_accept_regex
    if discover_update_resolv_conf is True:
      controller['discover_update_resolv_conf'] = 'true'
    elif discover_update_resolv_conf is False:
      controller['discover_update_resolv_conf'] = 'false'
    if local_ip is not None:
      controller['local_ip'] = local_ip
    if local_netmask is not None:
      controller['local_netmask'] = local_netmask
    if local_gateway is not None:
      controller['local_gateway'] = local_gateway
    controller_uuid = _generate_uuid()
    tx.insert('Controller', controller_uuid, controller)

    # Find the bridge with that name.
    bridge_rows = self._select('Bridge', [_bridge_id_where_clause(bridge_id)],
                               ['_uuid'])
    if len(bridge_rows) != 1:
      raise Exception('no bridge with id %s' % bridge_id)
    bridge_uuid = bridge_rows[0]['_uuid'][1]

    # Add the controller to the bridge.
    tx.set_insert('Bridge', bridge_uuid, 'controller',
                  ['uuid', controller_uuid])

    # Trigger ovswitchd to reload the configuration:
    tx.increment('Open_vSwitch', None, ['next_cfg'])

    if external_ids:
      external_ids_str = ', '.join(['%s=%s' % ext_id
                                    for ext_id in external_ids.iteritems()])
      tx.add_comment('added controller %s to bridge %s with external ids %s' %
                     (target, bridge_id, external_ids_str))
    else:
      tx.add_comment('added controller %s to bridge %s' %
                     (target, bridge_id))

    return self._do_json_rpc(tx)

  def del_bridge_openflow_controllers(self, bridge_id):
    """Delete all the OpenFlow controller targets for a bridge.

    Args:
      bridge_id: The identifier of the bridge to udpate.
    """
    tx = Transaction(self._database)

    bridge_rows = self._select('Bridge', [_bridge_id_where_clause(bridge_id)],
                               ['_uuid', 'controller'])
    for bridge_row in bridge_rows:
      bridge_uuid = bridge_row['_uuid'][1]
      controllers = bridge_row['controller']
      # TODO: Write an UUID set iterator to do that iteration here and
      # in del_bridge.
      if controllers[0] == 'uuid':
        controllers = [controllers]
      elif controllers[0] == 'set':
        controllers = controllers[1]
      for controller_uuid in controllers:
        tx.delete('Controller', controller_uuid[1])
        tx.set_delete('Bridge', bridge_uuid, 'controller', controller_uuid)

    # Trigger ovswitchd to reload the configuration:
    tx.increment('Open_vSwitch', None, ['next_cfg'])

    tx.add_comment('deleted controllers for bridge with id %s' % (bridge_id,))

    return self._do_json_rpc(tx)

  def has_bridge(self, bridge_id):
    """Determine whether a bridge with a given name exists.
    
    Args:
      bridge_id: the identifier of the bridge whose existence is queried.
    
    Returns:
      True if the the OVS database has a bridge with a given id, else False.
    """
    bridge_rows = self._select('Bridge', [_bridge_id_where_clause(bridge_id)],
                               ['_uuid'])
    return len(bridge_rows) > 0

  def del_bridge(self, bridge_id):
    """Delete the bridge with the given name.

    Args:
      bridge_id: The identifier of the bridge to delete.
    """
    tx = Transaction(self._database)

    # Delete all bridges with that id, and all their ports and interfaces.
    bridge_rows = self._select('Bridge', [_bridge_id_where_clause(bridge_id)],
                               ['_uuid', 'ports'])
    for bridge_row in bridge_rows:
      bridge_uuid = bridge_row['_uuid'][1]
      tx.delete('Bridge', bridge_uuid)
      # The 'Open_vSwitch' table should contain only one row, so pass None as
      # the UUID to update all the rows in there.
      # Delete the bridge UUID from the set of activated bridges:
      tx.set_delete('Open_vSwitch', None, 'bridges', ['uuid', bridge_uuid])

      ports = bridge_row['ports']
      if ports[0] == 'uuid':
        ports = [ports]
      elif ports[0] == 'set':
        ports = ports[1]
      for port_uuid in ports:
        tx.delete('Port', port_uuid[1])
        port_row = self._select('Port', [['_uuid', '==', port_uuid]],
                                ['_uuid', 'interfaces'])[0]
        ifs = port_row['interfaces']
        if ifs[0] == 'uuid':
          ifs = [ifs]
        for if_uuid in ifs:
          tx.delete('Interface', if_uuid[1])

    # Trigger ovswitchd to reload the configuration:
    tx.increment('Open_vSwitch', None, ['next_cfg'])

    tx.add_comment('deleted bridge with id %s' % (bridge_id,))

    return self._do_json_rpc(tx)

  def get_datapath_external_id(self, bridge_id, external_id_key):
    """Get an external id associated with a bridge given its id.

    Args:
      bridge_id: The identifier of the bridge.
      external_id_key: The key of the external id to look up, as a string.

    Returns:
      The value of the external id, as a string.  None if no bridge
      with that datapath id exists, or if the bridge has no external
      id with that key.
    """
    bridge_rows = self._select(
        'Bridge', [_bridge_id_where_clause(bridge_id)],
        ['_uuid', 'external_ids'])
    for bridge_row in bridge_rows:
      external_ids = self._ovs_map_to_dict(bridge_row['external_ids'])
      return external_ids.get(external_id_key)

  def get_port_external_id_by_name(self, name, external_id_key):
    """Get an external id associated with a port given its name.

    Args:
      name: The name of the port.
      external_id_key: The key of the external id to look up, as a string.

    Returns:
      The value of the external id, as a string.  None if no port with
      that name exists, or if the port has no external id with that
      key.
    """
    port_rows = self._select(
        'Port', [['name', '==', name]],
        ['_uuid', 'external_ids'])
    for port_row in port_rows:
      external_ids = self._ovs_map_to_dict(port_row['external_ids'])
      return external_ids.get(external_id_key)

  def get_port_external_id_by_port_num(self, bridge_id, port_num,
                                      external_id_key):
    """Get an external id associated with a port given port number.

    Args:
      bridge_id: The identifier of the bridge that contains the port.
      port_num: The number of the port.
      external_id_key: The key of the external id to look up, as a string.

    Returns:
      The value of the external id, as a string.  None if no bridge
      with that id exists, or if no port with that number exists in
      that bridge, or if the port has no external id with that key.
    """
    bridge_rows = self._select('Bridge', [_bridge_id_where_clause(bridge_id)],
                               ['_uuid', 'ports'])
    for bridge_row in bridge_rows:
      # We found the bridge. Iterate on the ports to find the one with
      # that number.
      ports = bridge_row['ports']
      if ports[0] == 'uuid':
        ports = [ports]
      elif ports[0] == 'set':
        ports = ports[1]
      for port_uuid in ports:
        # The external_ids are in table Port.
        port_row = self._select('Port', [['_uuid', '==', port_uuid]],
                                ['_uuid', 'interfaces', 'external_ids'])[0]
        ifs = port_row['interfaces']
        if ifs[0] == 'uuid':
          ifs = [ifs]
        # The ofport port numbers are in table Interface. Iterate on
        # the interfaces of a port to find the interface with the
        # right port number.
        for if_uuid in ifs:
          if_row = self._select('Interface', [['_uuid', '==', if_uuid]],
                                ['_uuid', 'ofport'])[0]
          if int(if_row['ofport']) == port_num:
            # This interface has the right port number, so the
            # enclosing port is the right port.
            external_ids = self._ovs_map_to_dict(port_row['external_ids'])
            return external_ids.get(external_id_key)

  def _get_queue_row_by_queue_num(self, qos_uuid, queue_num):
    """Get the row associated with a queue for which given the number
    of the queue stands in the QoS.

    Args:
      qos_uuid: The UUID of the QoS that contains the queue.
      queue_num: The local number of the queue on the port.

    Returns:
      The row of the queue, as a dictionary. None if no QoS with that UUID
      exists, or if no queue with queue_num exists in that QoS.
    """
    qos_rows = self._select('QoS', _where_uuid_equals(qos_uuid),
                            ['_uuid', 'queues'])
    queue_uuid = None
    for qos_row in qos_rows:
      queue_uuids = self._ovs_map_to_dict(qos_row['queues'])
      queue_uuid = queue_uuids.get(queue_num)
      if queue_uuid is not None:
        queue_uuid = queue_uuid[1]
      else:
        return None
    if queue_uuid is not None:
      queue_rows = self._select('Queue', _where_uuid_equals(queue_uuid),
                                ['_uuid', 'external_ids'])
    if len(queue_rows) != 1:
      raise None
    return queue_rows[0]

  def get_queue_uuid_by_queue_num(self, qos_uuid, queue_num):
    """Get the UUID associated with a queue for which given the number
    of the queue stands in the QoS.

    Args:
      qos_uuid: The UUID of the QoS that contains the queue.
      queue_num: The local number of the queue on the port.

    Returns:
      The value of the UUID, as a string. None if no QoS with that UUID exists,
      or if no queue with number exists in that QoS.
    """
    queue_row = self._get_queue_row_by_queue_num(qos_uuid, queue_num)
    return queue_row.get('_uuid')[1]

  def get_queue_external_id_by_queue_num(self, qos_uuid,
                                         queue_num, external_id_key):
    """Get the external id associated with the queue for which given the number
    of the queue stands in the QoS.

    Args:
      qos_uuid: The UUID of the QoS that contains the queue.
      queue_num: The local number of the queue on the port.
      external_id_key: The key of the external id to look up, as a string

    Returns:
      The value of the external id, as a string. None if no QoS with that UUID
      exists, or if no queue with number exists in that QoS, or if the queue has
      no external id with that key.
    """
    queue_row = self._get_queue_row_by_queue_num(qos_uuid, queue_num)
    queue_external_ids = queue_row.get('external_ids', {})
    return queue_row.get(external_id_key)

  def _get_qos_row_by_port_name(self, port_name):
    """Get the UUID of the QoS associated with a port for which the given name
    stands.

    Args:
      port_name: The name of the port to which the QoS is bound.

    Returns:
      The row of the QoS, as a dictionary. None if no port with the name exists,
      or if no QoS associated with the port.
    """
    port_rows = self._select('Port', [['name', '==', port_name]],
                             ['_uuid', 'qos'])
    if len(port_rows) != 1:
      return None
    qos_uuid = port_rows[0]['qos']
    qos_rows = self.select('QoS', _where_uuid_equals(qos_uuid), ['_uuid'])
    if len(qos_rows) != 1:
      return None
    qos_row = qos_rows[0]

    return qos_row

  def get_qos_uuid_by_port_name(self, port_name):
    """Get the UUID of the QoS associated with a port for which the given name
    stands.

    Args:
      port_name: The name of the port to which the QoS is bound.

    Returns:
      The UUID of the QoS, as a string. None if no port with the name exists,
      or if no QoS associated with the port.
    """
    qos_row = self._get_qos_row_by_port_name(port_name)
    return qos_row['_uuid'][1] if qos_row else None

  def _compose_qos(self, type='linux-htb', max_rate=None,
                   external_ids={}, queue_uuids={}):
    """Compose the dictionary representation of the QoS with temporary UUID.

    Args:
      type: The type of the QoS such as 'linux-htb' or 'linux-hfcs'. Defaults to
          'linux-htb'. i.e., use linux-hfcs as the QoS type.
      max_rate: The maximum rate shared by all queued traffic in bit/s. Defaults
          to None, i.e., no maximum rate.
      external_ids: The key-value pairs for use by external frameworks. Defaults
          to an empty dictionary, i.e., no external ids.
      queue_uuids: The key-value pairs which key is the number of the queue and
          value is the list which the first is 'uuid' and the second is the UUID
          of the queue. Defaults to an empty dictionary, i.e., no queues.

    Returns:
      A (qos_uuid, qos_row) tuple, where qos_uuid is the UUID of the QoS,
      as a string, and qos_row is the QoS row as a dict.
    """
    qos_uuid = _generate_uuid()

    other_config = {}
    if max_rate is not None:
      other_config['max-rate'] = str(max_rate)
    if external_ids:
      other_config['external_ids'] = self._dict_to_ovs_map(external_ids)
    qos_row = {'type': type}
    if queue_uuids:
      qos_row['queues'] = self._dict_to_ovs_map(queue_uuids)
    if other_config:
      qos_row['other_config'] =  self._dict_to_ovs_map(other_config)
    return qos_uuid, qos_row

  def add_qos_queues(self, type='linux-htb', max_rate=None,
                     external_ids={}, queues=[]):
    """Add the QoS and the queues at the same time.

    Args:
      type: The type of the QoS such as 'linux-htb' or 'linux-hfcs'. Default to
          'linux-htb', i.e., use 'linux-htb' as the QoS.
      max_rate: The maximum rate shared by all queued traffic in bit/s. Default
          to None, i.e., no maximum rate.
      external_ids: The key-value pairs for use by external frameworks. Default
          to an empty list, i.e., no external ids.
      queues: The queues to be added, as a list of dictionaries. Every queue is
          represented as a dictionary, with the following optional keys:
              max-rate: The maximum rate in bps.
              min-rate: The minimum rate in bps.
              burst: The burst rate in bits. (for linux-hfsc)
              priority: The priority for the queue, which is a nonnegative
                  32-bit integer. (for linux-hfsc)
          Default to an empty list, i.e., no queues to be set.
    """
    tx = Transaction(self._database)
    queue_uuids = []
    for queue in queues:
      max_rate = queue.get('max-rate')
      min_rate = queue.get('min-rate')
      burst = queue.get('burst')
      priority = queue.get('priority')
      queue_uuid, queue_row = self._compose_queue(
            max_rate, min_rate, burst, priority)
      _uuid_list_append(queue_uuids, queue_uuid)
      tx.insert('Queue', queue_uuid, queue_row)
      tx.add_comment('created Queues with uuid %s' % queue_uuid)

    # Create indexed queue_uuids. The number 0 is reserved as no queue in the
    # Open vSwitch specification.
    queue_uuids = dict(zip(range(1, len(queue_uuids)+1), queue_uuids))
    qos_uuid, qos_row = self._compose_qos(
      type, max_rate, external_ids, queue_uuids)
    tx.insert('QoS', qos_uuid, qos_row)
    tx.add_comment('created QoS with uuid %s' % qos_uuid)
    tx.increment('Open_vSwitch', None, ['next_cfg'])

    return self._do_json_rpc(tx)

  def set_port_qos(self, port_name, qos_uuid):
    """Set the QoS to the port.

    Args:
      port_name: The name of the port to be added.
      qos_uuid: The UUID of the QoS to add.
    """
    tx = Transaction(self._database)
    port_rows = self._select('Port', [['name', '==', port_name]], ['_uuid'])

    if len(port_rows) != 1:
      raise Exception('no port with name %s' % port_name)
    qos_rows = self._select('QoS', _where_uuid_equals(qos_uuid), ['_uuid'])
    if len(qos_rows) != 1:
      raise Exception('no port with name %s' % port_name)
    for port_row in port_rows:
      port_uuid = port_row['_uuid'][1]
      tx.set_insert('Port', port_uuid, 'qos', qos_rows[0]['_uuid'])
    tx.increment('Open_vSwitch', None, ['next_cfg'])

    return self._do_json_rpc(tx)

  def del_qos(self, qos_uuid, delete_queues=False):
    """Delete a QoS.

    The QoS is removed from any port on which it is set. If delete_queue is True,
    delete all queues bound to the QoS.

    Args:
      qos_uuid: The UUID of the QoS to delete.
      delete_queues: The flag whether queues the QoS has will be deleted or
          not. Defaults to False, i.e., no queues bound to the QoS will be
          deleted.
    """
    tx = Transaction(self._database)
    qos_rows = self._select('QoS', _where_uuid_equals(qos_uuid),
                            ['_uuid', 'queues'])

    if len(qos_rows) != 1:
      raise Exception('no QoS with uuid %s' % qos_uuid)
    tx.delete('QoS', qos_uuid)
    tx.add_comment('deleted QoS with uuid %s' % qos_uuid)
    # Delete all queues the QoS contains.
    if delete_queues:
      queues = self._ovs_map_to_dict(qos_rows[0]['queues'])
      for _, queue_uuid in queues.values():
        tx.delete('Queue', queue_uuid)
    # Delete the QoS from the ports.
    port_rows = self._select('Port', [['qos', 'includes', ['uuid', qos_uuid]]],
                              ['_uuid', 'qos'])
    for port_row in port_rows:
      port_uuid = port_row['_uuid'][1]
      qos_value = port_rows['qos'][1]
      tx.set_delete('Port', port_uuid, 'qos', qos_value)
    tx.increment('Open_vSwitch', None, ['next_cfg'])

    return self._do_json_rpc(tx)

  def update_qos(self, qos_uuid, type='linux-htb', queue_uuids={},
                 max_rate=None, external_ids={}):
    """Update the QoS with given parameters.

    This will ignore ungiven parameters and update only given parameters.

    Args:
      qos_uuid : The UUID of the QoS to update.
      type: The type of queues such as 'linux-htb' or 'linux-hfcs'. Defaults to
          None. i.e., the type of the QoS will not be updated.
      queue_uuids: The key-value pairs which key is the number of the queue and
          value is the list which the first is 'uuid' and the second is the UUID
          of the queue. Defaults to an empty dictionary, i.e., no queues to be
          updated.
      max_rate: The maximum rate shared by all queued traffic in bit/s. Defaults
          to None. i.e., no maximum rate.
      external_ids: The key-value pairs for use by external frameworks. Defaults
          to an empty dictionary. i.e., no external ids.

    Returns:
      A (qos_uuid, qos_row) tuple, where qos_uuid is the UUID of the QoS, as a
      string, and qos_row is the QoS row as a dict.
    """
    tx = Transaction(self._database)
    qos_rows = self._select('QoS',_where_uuid_equals(qos_uuid),
                            ['_uuid', 'queues', 'other_config', 'external_ids'])
    if len(qos_rows) != 1:
      raise Exception('no QoS with uuid %s' % qos_uuid)
    qos_row = qos_rows[0]
    # Merge pairs to update and existed pairs
    other_config = {'max-rate': str(max_rate)} if max_rate else {}
    updated_qos_row = {}
    if type is not None:
      updated_qos_row['type'] =  type
    if queue_uuids:
      updated_qos_row['queues'] = self._dict_to_ovs_map(queue_uuids)
    updated_qos_row = dict(
      (k, v) for k, v in updated_qos_row.items() if v is not None)
    if other_config:
      updated_qos_row['other_config'] = self._dict_to_ovs_map(other_config)
    if external_ids:
      updated_qos_row['external_ids'] = self._dict_to_ovs_map(external_ids)
    qos_row.update(updated_qos_row)
    tx.update('QoS', qos_uuid, qos_row)
    tx.increment('Open_vSwitch', None, ['next_cfg'])

    return self._do_json_rpc(tx)

  def clear_qos(self, port_name, delete_qos=True):
    """Clear all the port's QoS.

    If delete_qos is True, delete all QoSs from the port.

    Args:
      port_name: The name of the port to be cleared.
      delete_qos: The flag whether The QoS will be deleted or not. Defaults
          to False. i.e., Not to be deleted.
    """
    tx = Transaction(self._database)
    port_rows = self._select('Port', [['name', '==', port_name]],
                             ['_uuid', 'qos'])

    if len(port_rows) != 1:
      raise Exception('no port with name %s' % port_name)
    for port_row in port_rows:
      port_uuid = port_row['_uuid'][1]
      # tx.set_delete('Port', port_uuid, 'qos', port_row['qos'])
      if delete_qos:
        qos_uuid = port_row['qos']
        tx.delete('QoS', qos_uuid)
        tx.add_comment('deleted the QoS with uuid %s ' % qos_uuid)
      port_row['qos'] = self._dict_to_ovs_map({})
      tx.update('Port', port_uuid, port_row)
    tx.increment('Open_vSwitch', None, ['next_cfg'])

    return self._do_json_rpc(tx)

  def _compose_queue(self, max_rate, min_rate=None, burst=None, priority=None,
                     external_ids={}):
    """Compose the dictionary representation of a queue with the temporary UUID.

    Args:
      max_rate: The integer of the maximum rate for the queue.
      min_rate: The integer of the minimum rate for the queue. Defaults to None,
          i.e., no minimum rate.
      burst: The burst size in bits (for linux-hfsc). Defaults to None, i.e., no
          burst.
      priority: The priority of the queue (for linux-hfsc). Defaults to None,
          i.e., no priority.
      external_ids: The key-value pairs for use by external frameworks. Defaults
          to an empty dictionary, i.e., no external ids.

    Returns:
      A (queue_uuid, queue_row) tuple, where queue_uuid is the UUID of the
      queue, as a string, and queue_row is the queue row as a dictionary.
    """
    queue_uuid = _generate_uuid()
    queue_row = {}

    other_config = {'max-rate': max_rate,
                    'min-rate': min_rate,
                    'burst': burst,
                    'priority': priority}
    other_config = dict(
      (k, str(v)) for k, v in other_config.items() if v is not None)
    if external_ids:
      other_config['external_ids'] = self._dict_to_ovs_map(external_ids)
    if other_config:
      queue_row = {'other_config': self._dict_to_ovs_map(other_config)}
    return queue_uuid, queue_row

  def add_queue(self, max_rate, min_rate=None,
                burst=None, priority=None, external_ids={}):
    """Add a queue with the specified uuid to OVSDB.

    Args:
      max_rate: A string of the maximum rate for the queue.
      min_rate: A string of the minimum rate for the queue. Defaults to None,
          i.e., no minimum rate.
      burst: The burst size in bits (for linux-hfsc). Defaults to None,
          i.e., no burst.
      priority: The priority of the queue (for linux-hfsc). Defaults to None,
          i.e., no priority.
      external_ids: The key-value pairs for use by external frameworks. Defaults
          to None, i.e., no external ids.
    """
    tx = Transaction(self._database)
    queue_uuid, queue_row = self._compose_queue(
      max_rate, min_rate, burst, priority, external_ids)
    tx.insert('Queue', queue_uuid, queue_row)
    tx.add_comment('deleted queue with uuid %s' % (queue_uuid))
    tx.increment('Open_vSwitch', None, ['next_cfg'])

    return self._do_json_rpc(tx)

  def set_qos_queues(self, qos_uuid, queue_uuids={}):
    """Set queues to the QoS which UUID is qos_uuid.

    Args:
      qos_uuid: The uuid of the QoS to be added.
      queue_uuids: The key-value pairs which key is the number of the queue and
          value is the list which the first is 'uuid' and the second is the UUID
          of the queue. Defaults to an empty dictionary, i.e., no queues.
    """
    tx = Transaction(self._database)
    qos_rows = self._select('QoS', _where_uuid_equals(qos_uuid), ['_uuid'])
    if len(qos_rows) != 1:
      raise Exception('no QoS with uuid %s' % qos_uuid)
    queues = self._dict_to_ovs_map(queue_uuids)
    tx.update('QoS', qos_uuid, {'queues': queues})
    tx.increment('Open_vSwitch', None, ['next_cfg'])

    return self._do_json_rpc(tx)

  def del_queue(self, queue_uuid):
    """Delete a queue which UUID is queue_uuid.

    You have to unbound the queue from associated QoSs before deleting it.
    This design decision is based on the specification of OVSDB.

    Args:
      queue_uuid: The uuid of the queue to delete.
    """
    tx = Transaction(self._database)
    queue_rows = self._select('Queue', _where_uuid_equals(queue_uuid),
                              ['_uuid'])

    if len(queue_rows) != 1:
      raise Exception('no queue with uuid %s' % queue_uuid)
    # TODO(tfukushima): Remove references of the queue from all associated
    # QoSs.
    # If you would like to remove references of the queue form QoSs, please read
    # comments on the code. That code needs the imporovement of performance by
    # selecting the minimal set of QoS rows like below.
    #
    # qos_rows = self._select('QoS', [['queues', 'includes',
    #    ['map', [[<ANY>, ['uuid', queue_uuid]]]]]], ['_uuid'])
    #
    # However, the OVSDB specification doesn't support wildcards like <ANY>
    # above.
    #
    # qos_rows = self._select('QoS', [['queues', '!=', []]], ['_uuid'])
    # for qos_row in qos_rows:
    #   qos_uuid = qos_uuid['_uuid'][1]
    #   queue_uuids = self._ovs_map_to_dict(qos_row['queues'])
    #   queue_uuids = dict([(index, [t, _queue_uuid])
    #                      for index, (t, _queue_uuid) in queue_uuids.items()
    #                      if _queue_uuid != queue_uuid])
    #   qos_row['queues'] = self._dict_to_ovs_map(queue_uuids)
    #   tx.update('QoS', qos_uuid, qos_row)
    tx.delete('Queue', queue_uuid)
    tx.add_comment('deleted queue with uuid %s' % (queue_uuid))
    tx.increment('Open_vSwitch', None, ['next_cfg'])

    return self._do_json_rpc(tx)

  def update_queue(self, queue_uuid, max_rate=None,
                   min_rate=None, burst=None, priority=None, external_ids={}):
    """Update the queue with given parameters.

    Args:
      queue_uuid: The UUID of the queue to update.
      max_rate: A string of the maximum rate for the queue. Defaults to None,
          i.e., maximum rate will not be updated.
      min_rate: A string of the minimum rate for the queue. Defaults to None,
          i.e., minimum rate will not be updated.
      burst: The burst size in bits (for linux-hfsc). Defaults to None,
          i.e., burst will not be updated.
      priority: The priority of the queue (for linux-hfsc). Defaults to None,
          i.e., priority will not be updated.
      external_ids: The key-value pairs for use by external frameworks. Defaults
          to an empty dictionary, i.e., external ids  will not be updated.
    """
    tx = Transaction(self._database)
    queue_rows = self._select('Queue', _where_uuid_equals(queue_uuid),
                              ['_uuid', 'other_config', 'external_ids'])

    if len(queue_rows) != 1:
      raise Exception('no queue with uuid %s' % queue_uuid)
    queue_row = queue_rows[0]
    # Merge pairs to update and existed pairs.
    # TODO(tfukushima): do you have any smarter idea?
    other_config = self._ovs_map_to_dict(queue_row.get('other_config', {}))
    # Update other_config.
    updated_other_config = {'max-rate': max_rate,
                            'min-rate': min_rate,
                            'burst': burst,
                            'priority': priority}
    # Filter update dictionary and stringify its value.
    updated_other_config = dict(
      (k, str(v)) for k, v in updated_other_config.items() if v is not None)
    other_config.update(updated_other_config)
    # Update external_ids.
    updated_external_ids = self._ovs_map_to_dict(
      queue_row.get('external_ids', {}))
    updated_external_ids = dict(
      (k, str(v)) for k, v in updated_external_ids.items() if v is not None)
    external_ids = external_ids.update(updated_external_ids)
    # Finally, update the queue row.
    if other_config:
      queue_row['other_config'] = self._dict_to_ovs_map(other_config)
    if external_ids:
      queue_row['external_ids'] = self._dict_to_ovs_map(external_ids)
    tx.update('Queue', queue_uuid, queue_row)
    tx.increment('Open_vSwitch', None, ['next_cfg'])

    return self._do_json_rpc(tx)

  def clear_queues(self, qos_uuid, delete_queues=True):
    """Clear all the queues bound to the QoS .

    If delete_queues is True, delete them except when they are refered from
    other QoSs.

    Args:
      qos_uuid: The uuid of the port to be cleared.
      delete_queues: The boolean whether to delete queues or not. Defaults to
          False. i.e., Not to delete queues but only disassociate.
    """
    tx = Transaction(self._database)
    qos_rows = self._select('QoS', _where_uuid_equals(qos_uuid),
                            ['_uuid', 'queues'])

    if len(qos_rows) != 1:
      raise Exception('no QoS with uuid %s' % qos_uuid)
    qos_empty_queues = {'queues': self._dict_to_ovs_map({})}
    for qos_row in qos_rows:
      if delete_queues:
        queues = self._ovs_map_to_dict(qos_row['queues'])
        for _, queue_uuid in queues.values():
          tx.delete('Queue', queue_uuid)
          tx.add_comment('deleted the Queue which UUID is %s ' % queue_uuid)
      tx.update('QoS', qos_row['_uuid'][1], qos_empty_queues)
    tx.increment('Open_vSwitch', None, ['next_cfg'])

    return self._do_json_rpc(tx)


  def _select_by_external_id(self, table, key, val, columns):
    """Get rows of columns in table that contains key-val pair in the
    external_ids column.
   	
    Args:
      table: The name of the table containing the rows to select.
      key: key to seek in the external_ids column.
      val: value to seek in the external_ids column.
      columns: The list of columns to return.
   	
    Returns:
      The list of selected rows.
    """
    tx = Transaction(self._database)
    tx.select(table, [['external_ids', 'includes',
                       self._dict_to_ovs_map({key: val})]], columns)
    return self._do_json_rpc(tx)[0]['rows']


  def get_bridge_names_by_external_id(self, key, val):
    """Get a list of the names of the bridges that contains an external_id
    key-val pair.
   	
    Args:
      key: key to seek in the external_ids column.
      val: value to seek in the external_ids column.
   	
    Returns:
      A list of bridge names.
    """
    rows = self._select_by_external_id('Bridge', key, val, ['name'])
    names = []
    for row in rows:
      names.append(str(row.get('name')))
    return names


  def get_bridge_uuids_by_external_id(self, key, val):
    """Get a list of the UUID of the bridges that contains an external_id
    key-val pair..
   	
    Args:
      key: key to seek in the external_ids column.
      val: value to seek in the external_ids column.
   	
    Returns:
      A list of bridge UUIDs.
    """
    rows = self._select_by_external_id('Bridge', key, val, ['_uuid'])
    uuids = []
    for row in rows:
      uuids.append(str(row.get('_uuid')[1]))
    return uuids
   	
   	
  def get_port_names_by_external_id(self, key, val):
    """Get a list of the names of the ports that contains an external_id
    key-val pair.
   	
    Args:
      key: key to seek in the external_ids column.
      val: value to seek in the external_ids column.
   	
    Returns:
      A list of port names.
    """
    rows = self._select_by_external_id('Port', key, val, ['name'])
    names = []
    for row in rows:
      names.append(str(row.get('name')))
    return names
   	
   	
  def get_port_uuids_by_external_id(self, key, val):
    """Get a list of the UUIDs of the ports that contains an external_id
    key-val pair.
   	
    Args:
      key: key to seek in the external_ids column.
      val: value to seek in the external_ids column.

    Returns:
      A list of port UUIDs.
    """
    rows = self._select_by_external_id('Port', key, val, ['_uuid'])
    uuids = []
    for row in rows:
      uuids.append(str(row.get('_uuid')[1]))
    return uuids


  def _set_external_id(self, table, uuid, key, val):
    """Sets the external_id colunm's key to val for the record with uuid in
    table.
   	
    Args:
      table: The name of the table containing the rows to select.
      uuid: _uuid value of the record to update.
      key: key to update in the external_ids column.
      val: value to set for the key of the external_ids column.

    Returns:
      True if successful, False otherwise.
    """
    tx = Transaction(self._database)
    tx.update(table, uuid, {'external_ids': self._dict_to_ovs_map({key: val})})
    return (int(self._do_json_rpc(tx)[0]['count']) == 1)


  def set_port_external_id(self, port_uuid, key, val):
    """Sets the key of external port ID of the Port with uuid of port_uuid to
    val.  Port record must exist for the update to succeed.  If the key does
    not exist in external_ids, it will create one.
   	
    Args:
      port_uuid: uuid of the Port record to update.
      key: key to update in the external_ids column.
      val: value to set for the key of the external_ids column.
   	
    Returns:
      True if successful, False otherwise.
    """
    return self._set_external_id('Port', port_uuid, key, val)
   	

  def set_bridge_external_id(self, bridge_uuid, key, val):
    """Sets the key of external port ID of the Bridge with uuid of port_uuid
    to val.  Bridge record must exist for the update to succeed.  If the key
    does not exist in external_ids, it will create one.

    Args:
      bridge_uuid: uuid of the Bridge record to update.
      key: key to update in the external_ids column.
      val: value to set for the key of the external_ids column.

    Returns:
      True if successful, False otherwise.
    """
    return self._set_external_id('Bridge', bridge_uuid, key, val)
   	

class Transaction(object):
  """A transaction to be performed by an Open vSwitch database server.
  """

  def __init__(self, database):
    """Create a new transaction.

    Args:
      database: The name of the mutated database.
    """
    self._database = database
    self._dry_run = False
    self._comments = []
    self._row_selections = []
    self._row_deletions = []
    self._row_insertions = []
    self._row_updates = []
    self._row_mutations = []

  def set_dry_run(self):
    self._dry_run = True

  def add_comment(self, comment):
    """Add a comment to the log on transaction success.

    Args:
      comment: The comment string.
    """
    self._comments.append(comment)

  def create_jsonrpc_request(self, id):
    """Get a JSON-encodable representation of this transaction's changes.

    Args:
      id: An unambiguous JSON-RPC request ID assigned to the new request.

    Returns:
      A Python value that can be encoded into JSON to represent this transaction
      in a JSON-RPC call to a DB.
    """
    params = [self._database]
    # Get the UUIDs of inserted rows, to be substituted if referenced in the
    # same transaction.
    substs_uuids = [row_uuid for _, row_uuid, _ in self._row_insertions]
    # Add row selections.
    params.extend([{'op': 'select',
                   'table': table,
                   'where': _substitute_uuids(where, substs_uuids),
                   'columns': columns}
                   for table, where, columns in self._row_selections])
    # Add row deletions.
    params.extend([{'op': 'delete',
                   'table': table,
                   'where': _substitute_uuids(where, substs_uuids)}
                  for table, where in self._row_deletions])
    # Add row insertions.
    params.extend([{'op': 'insert',
                   'table': table,
                   'uuid-name': _get_uuid_name_from_uuid(row_uuid),
                   'row': _substitute_uuids(row, substs_uuids)}
                  for table, row_uuid, row in self._row_insertions])
    # Add row updates.
    params.extend([{'op': 'update',
                   'table': table,
                   'where': _substitute_uuids(where, substs_uuids),
                   'row': _substitute_uuids(row, substs_uuids)}
                  for table, where, row in self._row_updates])
    # Add mutations (increments, etc.).
    params.extend([{'op': 'mutate',
                   'table': table,
                   'where': _substitute_uuids(where, substs_uuids),
                   'mutations': _substitute_uuids(mutations, substs_uuids)}
                  for table, where, mutations in self._row_mutations])

    # Add comments.
    if self._comments:
      params.append({'op': 'comment',
                     'comment': '\n'.join(self._comments)})

    # Abort immediately in case this is a dry run.
    if self._dry_run:
      params.append({'op': 'abort'})

    # Return a 'transact' JSON-RPC request to perform those changes.
    return {'method': 'transact',
            'params': params,
            'id': id}

  def select(self, table, where, columns):
    """Select columns for the rows that match the 'where' clause.

    Args:
      table: The name of the table containing the rows to select.
      where: The JSON-encodable 'where' clauses to be matched by the rows.
      columns: The list of columns to return.
    """
    self._row_selections.append((table, where, columns))

  def delete(self, table, row_uuid):
    """Delete a row in this transaction.

    Args:
      table: The name of the table containing the row to delete.
      row_uuid: The UUID string of the row to delete.
    """
    if row_uuid is None:
      where = []
    else:
      where = _where_uuid_equals(row_uuid)
    self._row_deletions.append((table, where))

  def insert(self, table, row_uuid, row):
    """Insert a row in this transaction.

    Args:
      table: The name of the table to contain the inserted row.
      row_uuid: The UUID string of the row to insert.
      row: A dict of the column / values of the inserted row.
    """
    self._row_insertions.append((table, row_uuid, row))

  def update(self, table, row_uuid, row):
    """Update a row in this transaction.

    Args:
      table: The name of the table containing the row to update.
      row_uuid: The UUID string of the row to update.
      row: A dict of the column / values updated.
    """
    if row_uuid is None:
      where = []
    else:
      where = _where_uuid_equals(row_uuid)
    self._row_updates.append((table, where, row))

  def increment(self, table, row_uuid, columns):
    """Increment values in columns for a given row in this transaction.

    Args:
      table: The name of the table containing the row to update.
      row_uuid: The UUID string of the row to update.
      columns: The list of column names of the columns to increment.
    """
    if row_uuid is None:
      where = []
    else:
      where = _where_uuid_equals(row_uuid)
    self._row_mutations.append((table, where,
                                [[column, '+=', 1] for column in columns]))

  def set_insert(self, table, row_uuid, column, value):
    """Insert a value into a set column for a given row in this transaction.

    Args:
      table: The name of the table containing the row to update.
      row_uuid: The UUID string of the row to update.
      column: The set column to update.
      value: The value to insert into the set.
    """
    if row_uuid is None:
      where = []
    else:
      where = _where_uuid_equals(row_uuid)
    self._row_mutations.append((table, where, [[column, 'insert', value]]))

  def set_delete(self, table, row_uuid, column, value):
    """Delete a value from a set column for a given row in this transaction.

    Args:
      table: The name of the table containing the row to update.
      row_uuid: The UUID string of the row to update.
      column: The set column to update.
      value: The value to delete from the set.
    """
    if row_uuid is None:
      where = []
    else:
      where = _where_uuid_equals(row_uuid)
    self._row_mutations.append((table, where, [[column, 'delete', value]]))


class ServerConnectionFactory(object):
  """A factory of connections to an Open vSwitch database server.
  """

  def __init__(self, url, ext_id_key):
    """Initialize this factory of OVSDB connections.

    Args:
      url: The default identifier of the server to connect to.
      ext_id_key: The default key for any external id's that this
          object will look up.
    """
    self._url = url
    self._ext_id_key = ext_id_key

  def open_ovsdb_connection(self, url=None):
    """Open a connection to the Open vSwitch DB server at the given URL.

    The following URL format(s) are supported:
      'unix:$(file)s': Connect to the Unix domain server socket named file.

    Args:
      url: The identifier of the server to connect to. If None, the
          connection will be made to the url specified in __init__.

    Returns:
      A newly created ServerConnection object to connect to the server
      at the URL.
    """
    if url is None:
      url = self._url
    if url.startswith('unix:'):
      file = url[5:]
      if not os.path.exists(file):
        raise Exception('UNIX domain socket %s does not exist' % file)
    else:
      raise Exception('unsupported URL scheme: %s' % url)
    error, stream = ovs.stream.Stream.open_block(
        ovs.stream.Stream.open(url))
    if error:
      raise Exception("could not open %s: %s" % (url, os.strerror(error)))
    return ServerConnection('Open_vSwitch', ovs.jsonrpc.Connection(stream))

  def del_port(self, port_name, url=None):
    """Delete a port given its name.

    Args:
      port_name: The port name.
      url: The identifier of the server to connect to. If None, the
          connection will be made to the url specified in __init__.
    """
    conn = self.open_ovsdb_connection(url)
    conn.del_port(port_name)
    conn.close()

  def add_gre_port(self, dp_id, port_name, remote_ip, local_ip, gre_key,
                   url=None):
    """Add a GRE tunnel port into a datapath.

    Args:
      dp_id: The datapath ID.
      port_name: The name of the port and of the GRE interface to create.
      remote_ip: The tunnel remote endpoint's IP address.
      local_ip: The tunnel local endpoint's IP address, or None if any
          IP address of the local host can be used.
      gre_key: The GRE key of received and sent packets.
      url: The identifier of the server to connect to. If None, the
          connection will be made to the url specified in __init__.
    """
    conn = self.open_ovsdb_connection(url)
    conn.add_gre_port(dp_id, port_name, remote_ip, key=gre_key,
                      header_cache=False, local_ip=local_ip)
    conn.close()

  def get_datapath_uuid(self, dp_id, url=None, ext_id_key=None):
    """Get the UUID of the datapath with the given ID.

    Args:
      dp_id: The datapath ID.
      url: The identifier of the server to connect to. If None, the
          connection will be made to the url specified in __init__.
      ext_id_key: The key of the external id associate with the
          datapath.  If None, the ext_id_key specified in __init__ will
          be used for the lookup.

    Returns:
      The datapath's UUID object, or None if not found.
    """
    if ext_id_key is None:
      ext_id_key = self._ext_id_key
    conn = self.open_ovsdb_connection(url)
    uuid_str = conn.get_datapath_external_id(dp_id, ext_id_key)
    conn.close()
    return None if uuid_str is None else uuid.UUID(uuid_str)

  def get_port_uuid(self, dp_id, port_num, url=None, ext_id_key=None):
    """Get the UUID of a port given its number.

    Args:
      dp_id: The datapath ID.
      port_num: The number of the port to look up.
      url: The identifier of the server to connect to. If None, the
          connection will be made to the url specified in __init__.
      ext_id_key: The key of the external id associate with the
          port.  If None, the ext_id_key specified in __init__ will
          be used for the lookup.

    Returns:
      The port's UUID object, or None if not found.
    """
    if ext_id_key is None:
      ext_id_key = self._ext_id_key
    conn = self.open_ovsdb_connection(url)
    uuid_str = conn.get_port_external_id_by_port_num(dp_id, port_num,
                                                     ext_id_key)
    conn.close()
    return None if uuid_str is None else uuid.UUID(uuid_str)
