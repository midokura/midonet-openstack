# Copyright (C) 2010 Midokura KK

# IEEE 802 MAC address formatting and generation.

import random
import struct
import uuid


def mac_to_str(mac):
  """Transform a binary MAC address into a string.

  Args:
    mac: The binary MAC address to convert, as a 6-byte binary string.

  Returns:
    The string representation of the MAC address, in the form
    '01:23:45:67:89:ab'.
  """
  return ':'.join(['%02x' % ord(b) for b in mac])


def str_to_mac(mac):
  """Transform a MAC address string into its binary address.

  Args:
    mac: The string representation of the MAC address, in the form
        '01:23:45:67:89:ab'.

  Returns:
    The binary representation of the MAC address, as a 6-byte-long string.
  """
  return ''.join([chr(int(b, 16)) for b in mac.split(':')])


def generate_mac_address(oui=None):
  """Generate a random MAC address.

  The uniqueness of the generated MAC address must be verified by the
  caller.

  Args:
    oui: The Organizationally Unique Identifier to use in the
        generated MAC address, as a 24-bit binary string. The OUI must
        not have the multicast and locally administered bits set. If
        None (default), a locally administered address is generated.

  Returns:
    The generated MAC address, as a 48-bit binary string.
  """
  if oui is not None:
    # Get 24 random bits for the LSBs.
    bits = random.getrandbits(24)
    return oui + struct.pack('!BH', bits >> 16, bits & 0xffff)
  else:
    # Get 48 random bits, although we really only need 46 bits. Unset
    # the multicast bit, and set the locally administered bit.
    bits = random.getrandbits(48) & 0xfeffffffffff | 0x020000000000
    return struct.pack('!HL', bits >> 32, bits & 0xffffffff)


def is_mcast_eth(ethaddr):
  """Returns whether an Ethernet address is multicast.

  Args:
    ethaddr: Ethernet address to check, as a 6-byte array.
  """
  return (ord(ethaddr[0]) & 1) == 1
