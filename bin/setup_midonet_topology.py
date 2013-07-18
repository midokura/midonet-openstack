#!/usr/bin/env python

import argparse
import sys

from midonetclient.api import MidonetApi

PROVIDER_ROUTER_NAME = 'MidonetProviderRouter'
provider_tenant_id = None


def _get_or_create_provider_router(provider_tenant_id):
    """
    Get the provider router object, searching by name defined abouve.
    If not found, it'll create one.
    """

    routers = mido_api.get_routers(
        {'tenant_id': provider_tenant_id})

    for r in routers:
        if r.get_name() == PROVIDER_ROUTER_NAME:
            return r

    return mido_api.add_router()\
                   .tenant_id(provider_tenant_id)\
                   .name(PROVIDER_ROUTER_NAME)\
                   .create()

def setup_provider_devices(args):
    # Handle provider router
    provider_router = _get_or_create_provider_router(provider_tenant_id)

    # Handle Metadata devices
    print "provider_router_id=%s" %  provider_router.get_id()

def setup_fake_uplink(args):
    routers = mido_api.get_routers(
                    {'tenant_id': provider_tenant_id})

    for r in routers:
        if r.get_name() == 'MidonetProviderRouter':
            provider_router = r
            uplink_port =  provider_router.add_exterior_port()\
                                          .port_address('100.100.100.1')\
                                          .network_address('100.100.100.0')\
                                          .network_length(24).create()

    # get host id to create a vport if mapping
    f = open('/etc/midolman/host_uuid.properties')
    lines = f.readlines()
    host_uuid = filter(lambda x: x.startswith('host_uuid='),
                       lines)[0].strip()[len('host_uuid='):]

    mido_api.get_host(host_uuid).add_host_interface_port()\
                           .port_id(uplink_port.get_id())\
                           .interface_name('midonet').create()

    # Add default route to the uplink
    provider_router.add_route().type('Normal')\
                   .src_network_addr('0.0.0.0')\
                   .src_network_length(0)\
                   .dst_network_addr('0.0.0.0')\
                   .dst_network_length(0)\
                   .weight(100)\
                   .next_hop_gateway('100.100.100.2')\
                   .next_hop_port(uplink_port.get_id()).create()


def main():
    global provider_tenant_id
    global mido_api

    base_parser = argparse.ArgumentParser()
    base_parser.add_argument('-u', help='Midonet admin username',
            metavar='midonet_uri', type=str,
            default='http://localhost:8080/midonet-api')
    base_parser.add_argument('username', help='Midonet admin username',
                             type=str)
    base_parser.add_argument('password', help='Midonet admin password',
                             type=str)
    base_parser.add_argument('provider_tenant_id',
                             help='tenant_id of the provider',
                             type=str)

    subparsers = base_parser.add_subparsers(help='sub-command help')

    # parser for setup_provider_devices subcommand
    parser_pv_devices = subparsers.add_parser('provider_devices',
                                              help='set up provider devices')
    parser_pv_devices.set_defaults(func=setup_provider_devices)

    parser_fake_uplink = subparsers.add_parser('fake_uplink',
                                              help='set up fake uplink')
    parser_fake_uplink.set_defaults(func=setup_fake_uplink)


    args = base_parser.parse_args()

    username = args.username
    password = args.password
    provider_tenant_id = args.provider_tenant_id

    mido_api = MidonetApi(midonet_uri, username, password, provider_tenant_id)

    args.func(args)

if __name__ == '__main__':
    sys.exit(main())
