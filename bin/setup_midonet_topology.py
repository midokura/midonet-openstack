#!/usr/bin/env python

import argparse
import sys

from midonetclient.api import MidonetApi

from neutron.plugins.midonet.midonet_lib import MidoClient

PROVIDER_ROUTER_NAME = 'MidonetProviderRouter'
METADATA_ROUTER_NAME = 'OpenstackMetadataRouter'
METADATA_BRIDGE_NAME = 'OpenstackMetadataBridge'

mido_api = None
mido_client = None
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


def _ensure_metadata_devices():
    """When neutron-server runs for the first time,
    it creates metadata router, bridge, link between them,
    and a exterior bridge port.

    If they are already set up, store the references to the
    instance variables.
    """

    #
    # MDR
    #

    routers = mido_api.get_routers(
        {'tenant_id': provider_tenant_id})

    found = False
    for r in routers:
        if r.get_name() == METADATA_ROUTER_NAME:
            metadata_router = r
            found = True
            break

    if not found:
        # create MDR and an interior port.
        metadata_router = mido_api.add_router()\
                                  .tenant_id(provider_tenant_id)\
                                  .name(METADATA_ROUTER_NAME)\
                                  .create()

        mdr_port = metadata_router.add_interior_port()\
                                  .port_address('169.254.169.253')\
                                  .network_address('169.254.0.0')\
                                  .network_length(16)\
                                  .create()

        # Add a route to metadata server
        metadata_router.add_route().type('Normal')\
                                   .src_network_addr('0.0.0.0')\
                                   .src_network_length(0)\
                                   .dst_network_addr('169.254.169.254')\
                                   .dst_network_length(32)\
                                   .weight(100)\
                                   .next_hop_port(mdr_port.get_id())\
                                   .create()

        # Create chains for metadata router
        chains = mido_client.create_router_chains(metadata_router)


        # set chains to in/out filters
        metadata_router.inbound_filter_id(chains['in'].get_id())\
                            .outbound_filter_id(chains['out'].get_id())\
                            .update()

        # add port translation rules for tcp port 80 <-> 8775
        nat_targets = []
        nat_targets.append(
            {'addressFrom': '169.254.169.254',
             'addressTo': '169.254.169.254',
             'portFrom': 8775,
             'portTo': 8775
             })

        chains['in'].add_rule().nw_dst_address('169.254.169.254')\
                               .nw_dst_length(32)\
                               .tp_dst_start(80)\
                               .tp_dst_end(80)\
                               .type('dnat')\
                               .flow_action('accept')\
                               .nat_targets(nat_targets)\
                               .position(1)\
                               .create()

        chains['out'].add_rule().nw_src_address('169.254.169.254')\
                                .nw_src_length(32)\
                                .tp_src_start(8775)\
                                .tp_src_end(8775)\
                                .type('rev_dnat')\
                                .flow_action('accept')\
                                .position(1)\
                                .create()

    #
    # MDB
    #
    found = False
    for b in mido_api.get_bridges({'tenant_id': provider_tenant_id}):

        if b.get_name() == METADATA_BRIDGE_NAME:
            metadata_bridge = b
            found = True
            for p in b.get_ports():
                if p.get_type() == 'ExteriorBridge':
                    mdb_port = p


    if not found:
        # create MDB and an interior port on it, then link it to MDR
        metadata_bridge = mido_api.add_bridge()\
                                  .tenant_id(provider_tenant_id)\
                                  .name(METADATA_BRIDGE_NAME)\
                                  .create()

        mdb_port = metadata_bridge.add_interior_port().create()
        mdb_port.link(mdr_port.get_id())

        # create a exterior port on MDB
        mdb_port = metadata_bridge.add_exterior_port().create()

    return {'mdr': metadata_router, 'mdb': metadata_bridge, 'mdbp': mdb_port}



def setup_provider_devices(args):
    # Handle provider router
    provider_router = _get_or_create_provider_router(provider_tenant_id)

    # Handle Metadata devices
    md_devices =  _ensure_metadata_devices()
    print "provider_router_id=%s" %  provider_router.get_id()
    print 'metadata_router_id=%s' % md_devices['mdr'].get_id()
    print 'metadata_bridge_id=%s' % md_devices['mdb'].get_id()
    print 'metadata_bridge_port_id=%s' % md_devices['mdbp'].get_id()

def setup_fake_uplink(args):
    import pdb
    pdb.set_trace()
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
    global mido_client

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

    mido_api = MidonetApi('http://localhost:8080/midonet-api',
                          username, password, provider_tenant_id)
    mido_client = MidoClient(mido_api)

    args.func(args)

if __name__ == '__main__':
    sys.exit(main())
