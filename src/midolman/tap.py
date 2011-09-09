# Copyright (C) 2010 Midokura KK

import fcntl
import os
import socket
import struct

from midolman import ieee_802


# Constants defined in <linux/if_tun.h>.
_TUNSETNOCSUM   = 0x400454c8
_TUNSETDEBUG    = 0x400454c9
_TUNSETIFF      = 0x400454ca
_TUNSETPERSIST  = 0x400454cb
_TUNSETOWNER    = 0x400454cc
_TUNSETLINK     = 0x400454cd
_TUNSETGROUP    = 0x400454ce
_TUNGETFEATURES = 0x800454cf
_TUNSETOFFLOAD  = 0x400454d0
_TUNSETTXFILTER = 0x400454d1
_TUNGETIFF      = 0x800454d2
_TUNGETSNDBUF   = 0x800454d3
_TUNSETSNDBUF   = 0x400454d4
_IFF_TUN   = 0x0001
_IFF_TAP   = 0x0002
_IFF_NO_PI = 0x1000

# Constants defined in <linux/sockios.h>.
_SIOCGIFFLAGS   = 0x8913
_SIOCSIFFLAGS   = 0x8914
_SIOCSIFADDR    = 0x8916
_SIOCSIFNETMASK = 0x891c
_SIOCSIFMTU     = 0x8922
_SIOCSIFHWADDR  = 0x8924
_SIOCGIFHWADDR  = 0x8927

# Constants defined in <linux/if.h>.
_IFF_UP          = 0x1
_IFF_BROADCAST   = 0x2
_IFF_DEBUG       = 0x4
_IFF_LOOPBACK    = 0x8
_IFF_POINTOPOINT = 0x10
_IFF_NOTRAILERS  = 0x20
_IFF_RUNNING     = 0x40
_IFF_NOARP       = 0x80
_IFF_PROMISC     = 0x100
_IFF_ALLMULTI    = 0x200
_IFF_MASTER      = 0x400
_IFF_SLAVE       = 0x800
_IFF_MULTICAST   = 0x1000
_IFF_PORTSEL     = 0x2000
_IFF_AUTOMEDIA   = 0x4000
_IFF_DYNAMIC     = 0x8000
_IFF_LOWER_UP    = 0x10000
_IFF_DORMANT     = 0x20000
_IFF_ECHO        = 0x40000


# Functions to handle ifreq structs, as defined in <linux/if.h>.
def _create_ifreq_flags(name, flags):
    """Create an ifreq struct with the given ifr_name and ifr_flags value.

    Args:
        name: The interface name. May be None.
        flags: The value of the ifr_flags field.

    Returns:
        A new ifreq structure.
    """
    if name is None:
        name = ''
    if len(name) > 16:
        raise IOError('interface name is too long: %s' % name)
    return struct.pack('16sH', name, flags)


def _get_ifreq_name(ifreq):
    """Get the ifr_name field from an ifreq struct.

    Args:
        ifreq: The ifreq struct.

    Returns:
        The ifr_name field.
    """
    return ifreq[:16].strip('\x00')


def _get_ifreq_flags(ifreq):
    """Get the ifr_flags field from an ifreq struct.

    Args:
        ifreq: The ifreq struct.

    Returns:
        The ifr_flags field, as a short unsigned integer.
    """
    return struct.unpack('H', ifreq[16:18])[0]


def open_tap_if(name):
    """Open a TAP interface.

    Args:
        name: The name of the interface to create, e.g. 'tap0'.

    Returns:
        The file descriptor of the open socket to the TAP interface.
    """
    f = os.open('/dev/net/tun', os.O_RDWR)
    ifreq = fcntl.ioctl(f, _TUNSETIFF,
        _create_ifreq_flags(name, (_IFF_TAP | _IFF_NO_PI)))
    return f


def create_persistent_tap_if(name, owner=None, group=None, mac=None):
    """Create or setup a persistent TAP interface.

    If the interface already exists, it is setup with the given owner and group
    and set persistent.

    Creating a new interface requires running as user root, or with Linux
    capability CAP_NET_ADMIN.

    Args:
        name: If not None, the name of the interface to create, e.g. 'tap0'. If
            the name ends with '%d', e.g. 'tap%d', the string before '%d' is
            used as the prefix of the name of the created interface, chosen to
            be unique.  Otherwise, a new unique name is chosen.
        owner: The UID (user id) of the user owning the interface, as an
            integer value.  If None, the interface has no owner and is usable
            only by root.
        group: The GID (group id) of the group owning the interface, as an
            integer value.  If None, the interface has no owner and is usable
            only by root.
        mac: The MAC address of the interface, as a string in the form
            '01:23:45:67:89:ab'.  If None, an address is randomly chosen.

    Returns:
        The name of the interface actually created.

    Raises:
        IOError: If the interface cannot be created or setup.
    """
    # Create the interface.
    f = os.open('/dev/net/tun', os.O_RDWR)
    ifreq = fcntl.ioctl(f, _TUNSETIFF,
        _create_ifreq_flags(name, (_IFF_TAP | _IFF_NO_PI)))
    if_name = _get_ifreq_name(ifreq)
    # Set the owner and group.
    if owner is not None:
        fcntl.ioctl(f, _TUNSETOWNER, int(owner))
    if group is not None:
        fcntl.ioctl(f, _TUNSETGROUP, int(group))

    # Make it persistent.
    fcntl.ioctl(f, _TUNSETPERSIST, 1)
    os.close(f)

    if mac is not None:
        set_if_hardware_address(if_name, mac)

    return if_name


def destroy_persistent_tap_if(name):
    """Destroys a persistent TAP interface.

    Make the interface with the given name non-persistent, which in effect
    destroys it.

    Args:
        name: The name of the interface to destroy.

    Raises:
        IOError: If the interface cannot be destroyed, e.g. it doesn't exist.
    """
    # Create the interface.
    f = os.open('/dev/net/tun', os.O_RDWR)
    ifreq = fcntl.ioctl(f, _TUNSETIFF,
        _create_ifreq_flags(name, (_IFF_TAP | _IFF_NO_PI)))
    # Make it persistent.
    fcntl.ioctl(f, _TUNSETPERSIST, 0)
    os.close(f)


def _create_ifreq_hwaddr(name, family, hwaddr):
    """Create an ifreq struct with the given ifr_name and ifr_hwaddr values.

    Args:
        name: The interface name.  May be None.
        family: The value of the ss_family field of the ifr_hwaddr field, i.e.
            the identifier of the hardware address family.
        hwaddr: The value of the __data field of the ifr_hwaddr field.

    Returns:
        A new ifreq structure.
    """
    return _create_ifreq(name, _SIOCGIFHWADDR, family, hwaddr)


def _create_ifreq(name, flag, family, data):
    """Create an ifreq struct with the given ifr_name and ifr_* values.
       Cf. <linux/if.h> for the ifreq struct definition.

    Args:
        name: The interface name.  May be None.
        flag: The value of _SIO* flags.
        family: The value of the ss_family field of the ifreq, i.e.
            the identifier of the hardware address family.
        data: The value of the ifr_ifru field of the ifreq.

    Returns:
        A new ifreq structure.
    """
    if name is None:
        name = ''
    if len(name) > 16:
        raise IOError('interface name is too long: %s' % name)

    if flag == _SIOCSIFADDR or flag == _SIOCSIFNETMASK:
        if len(data) > 4:
            raise IOError('data is too long')
        # TODO(yoshi) : accept port number instead of putting 0?
        # Cf. <netinet/if.h> for sockaddr_in struct definition.
        return struct.pack('16sHH4s4s', name, family, 0, data, '0')
    elif flag == _SIOCSIFMTU:
        return struct.pack('16si', name, data)
    elif flag == _SIOCSIFHWADDR or flag == _SIOCGIFHWADDR:
        if len(data) > 126:
            raise IOError('data is too long')
        # Cf. <linux/socket.h> for the sockaddr struct definition.
        return struct.pack('16sH126s', name, family, data)


def _get_ifreq_hwaddr(ifreq):
    """Get the address in the ifr_hwaddr field from an ifreq struct.

    Args:
        ifreq: The ifreq struct.

    Returns:
        The address from the ifr_hwaddr field, formatted as a string in the
        form '01:23:45:67:89:ab'.
    """
    return ':'.join(['%02x' % ord(b) for b in ifreq[18:24]])


def _get_ifreq_hwaddr_family(ifreq):
    """Get the family in the ifr_hwaddr field from an ifreq struct.

    Args:
        ifreq: The ifreq struct.

    Returns:
        The family code from the ifr_hwaddr field, as a short unsigned integer.
    """
    return struct.unpack('H', ifreq[16:18])[0]


def set_if_address(name, addr, prefix_len):
    """Set the address of a network interface.

    Args:
        name: The name of the network interface, e.g. 'eth0'.
        addr: The IPv4 address to set as a string.
        prefix_len: The prefix length of the address as an integer.
    """
    addr = socket.inet_pton(socket.AF_INET, addr)
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    ifreq = fcntl.ioctl(sock.fileno(), _SIOCSIFADDR,
                        _create_ifreq(name, _SIOCSIFADDR, socket.AF_INET,
                                      addr))

    mask = struct.pack('!l', (~0 << (32 - prefix_len)))
    ifreq = fcntl.ioctl(sock.fileno(), _SIOCSIFNETMASK,
                        _create_ifreq(name, _SIOCSIFNETMASK, socket.AF_INET,
                                      mask))
    sock.close()


def set_if_mtu(name, mtu):
    """Set the address of a network interface.

    Args:
        name: The name of the network interface, e.g. 'eth0'.
        mtu: The mtu value as an integer.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    ifreq = fcntl.ioctl(sock.fileno(), _SIOCSIFMTU,
                        _create_ifreq(name, _SIOCSIFMTU, 0, mtu))
    sock.close()


# Cf. the netdevice(7) manpage.
def get_if_hardware_address(name):
    """Get the hardware address of a network interface.

    Args:
        name: The name of the network interface, e.g. 'eth0'.

    Returns:
        The MAC address of the interface, in the form '01:23:45:67:89:ab'.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    ifreq = fcntl.ioctl(sock.fileno(), _SIOCGIFHWADDR,
                        _create_ifreq_hwaddr(name, 0, ''))
    sock.close()
    return _get_ifreq_hwaddr(ifreq)


def set_if_hardware_address(name, addr):
    """Set the hardware address of a network interface.

    Args:
        name: The name of the network interface, e.g. 'eth0'.
        addr: The MAC address to set, as a string in the form
            '01:23:45:67:89:ab'.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    # First make a request to get the current address, and more importantly the
    # current address family.
    ifreq = fcntl.ioctl(sock.fileno(), _SIOCGIFHWADDR,
                        _create_ifreq_hwaddr(name, 0, ''))
    family = _get_ifreq_hwaddr_family(ifreq)
    ifreq = fcntl.ioctl(sock.fileno(), _SIOCSIFHWADDR,
                        _create_ifreq_hwaddr(name, family,
                                             ieee_802.str_to_mac(addr)))
    sock.close()


def set_if_flags(name, up=None, broadcast=None, debug=None, loopback=None,
                 pointopoint=None, notrailers=None, running=None, noarp=None,
                 promisc=None, allmulti=None, master=None, slave=None,
                 multicast=None, portsel=None, automedia=None, dynamic=None,
                 lower_up=None, dormant=None, echo=None):
    # TODO: doc
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    ifreq = fcntl.ioctl(sock.fileno(), _SIOCGIFFLAGS,
                        _create_ifreq_flags(name, 0))
    flags = _get_ifreq_flags(ifreq)
    if up is True: flags = flags | _IFF_UP
    elif up is False: flags = flags & ~_IFF_UP
    if broadcast is True: flags = flags | _IFF_BROADCAST
    elif broadcast is False: flags = flags & ~_IFF_BROADCAST
    if debug is True: flags = flags | _IFF_DEBUG
    elif debug is False: flags = flags & ~_IFF_DEBUG
    if loopback is True: flags = flags | _IFF_LOOPBACK
    elif loopback is False: flags = flags & ~_IFF_LOOPBACK
    if pointopoint is True: flags = flags | _IFF_POINTOPOINT
    elif pointopoint is False: flags = flags & ~_IFF_POINTOPOINT
    if notrailers is True: flags = flags | _IFF_NOTRAILERS
    elif notrailers is False: flags = flags & ~_IFF_NOTRAILERS
    if running is True: flags = flags | _IFF_RUNNING
    elif running is False: flags = flags & ~_IFF_RUNNING
    if noarp is True: flags = flags | _IFF_NOARP
    elif noarp is False: flags = flags & ~_IFF_NOARP
    if promisc is True: flags = flags | _IFF_PROMISC
    elif promisc is False: flags = flags & ~_IFF_PROMISC
    if allmulti is True: flags = flags | _IFF_ALLMULTI
    elif allmulti is False: flags = flags & ~_IFF_ALLMULTI
    if master is True: flags = flags | _IFF_MASTER
    elif master is False: flags = flags & ~_IFF_MASTER
    if slave is True: flags = flags | _IFF_SLAVE
    elif slave is False: flags = flags & ~_IFF_SLAVE
    if multicast is True: flags = flags | _IFF_MULTICAST
    elif multicast is False: flags = flags & ~_IFF_MULTICAST
    if portsel is True: flags = flags | _IFF_PORTSEL
    elif portsel is False: flags = flags & ~_IFF_PORTSEL
    if automedia is True: flags = flags | _IFF_AUTOMEDIA
    elif automedia is False: flags = flags & ~_IFF_AUTOMEDIA
    if dynamic is True: flags = flags | _IFF_DYNAMIC
    elif dynamic is False: flags = flags & ~_IFF_DYNAMIC
    if lower_up is True: flags = flags | _IFF_LOWER_UP
    elif lower_up is False: flags = flags & ~_IFF_LOWER_UP
    if dormant is True: flags = flags | _IFF_DORMANT
    elif dormant is False: flags = flags & ~_IFF_DORMANT
    if echo is True: flags = flags | _IFF_ECHO
    elif echo is False: flags = flags & ~_IFF_ECHO
    ifreq = fcntl.ioctl(sock.fileno(), _SIOCSIFFLAGS,
                        _create_ifreq_flags(name, flags))
    sock.close()
