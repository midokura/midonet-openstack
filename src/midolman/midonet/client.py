#!/usr/bin/env python
#
# Copyright (C) 2011 Midokura KK
#
# Midonet REST API client

import sys
import httplib2
import readline
import json


class MidonetClient:

    def __init__(self, token, host='127.0.0.1', port=8080, app='midolmanj-mgmt'):
        self.h = httplib2.Http()
        self.token = token
        self.host = host
        self.port = port
        self.app = app

    def _do_request(self, location, method, body='{}'):

        url = "http://%s:%d/%s/v1/%s" % (self.host, self.port, self.app, location)
        #url = MIDONET_API_SERVER + '/midolmanj-mgmt/v1/%s' % location
        print "-------------------"
        print "URL: ", url
        print "method: ", method
        print "body: ", body

        response, content = self.h.request(url, method, body, headers={
        "Content-Type": "application/json",
        "HTTP_X_AUTH_TOKEN": self.token} 
        )

        try:
            resp = json.loads(content)
        except:
            # FIXME: Fix this.  Just for now, we don't handle error message well.
            resp = None

        return response, resp 

    # tenants
    def create_tenant(self, uuid=None):
        body = '{}'
        if uuid:
            body ='{"id": "%s"}' % uuid
            print body
    
        return self._do_request("tenants", "POST", body)

    # bridges
    def create_bridge(self, tenant_id, name):
        assert tenant_id != None
        assert name != None

        body = '{"name": "%s" }' % name
        location = 'tenants/%s/bridges' % tenant_id
        return self._do_request(location, "POST", body)

    def get_bridge(self, bridge_id):
        assert bridge_id != None

        location = 'bridges/%s' % bridge_id
        return self._do_request(location, "GET")

    def update_bridge(self, bridge_id, name):
        assert bridge_id != None
        assert name != None

        location = 'bridges/%s' % bridge_id
        body = '{"name": "%s"}' % name
        return self._do_request(location, "PUT", body)

    def index_bridge(self, tenant_id):
        assert tenant_id != None
        location = 'tenants/%s/bridges' % tenant_id
        return self._do_request(location, "GET")

    def delete_bridge(self, bridge_id):
        assert bridge_id != None
        location = 'bridges/%s' % bridge_id
        return self._do_request(location, "DELETE")


    # bridge ports
    def create_bridge_port(self, bridge_id):
        assert bridge_id != None
        location = 'bridges/%s/ports' % bridge_id
        return self._do_request(location, "POST")

    def get_bridge_port(self, port_id):
        assert port_id != None
        location = 'ports/%s' % port_id
        return self._do_request(location, "GET")

    def list_bridge_port(self, bridge_id):
        assert bridge_id != None
        location = 'bridges/%s/ports' % bridge_id
        return self._do_request(location, "GET")

    def delete_bridge_port(self, port_id):
        assert port_id != None
        location = 'ports/%s' % port_id
        return self._do_request(location, "DELETE")


    # routers
    def create_router(self, tenant_id, name):
        assert tenant_id != None
        assert name != None
        location = 'tenants/%s/routers' % tenant_id
        body ='{"name": "%s"}' % name
        return self._do_request(location, "POST", body)

    def get_router(self, router_id):
        assert router_id != None
        location = 'routers/%s' % router_id
        return self._do_request(location, "GET")

    def list_router(self, tenant_id):
        assert tenant_id != None
        location = 'tenants/%s/routers' % tenant_id
        return self._do_request(location, "GET")

    def update_router(self, router_id, name):
        assert router_id != None
        assert name != None
        location = 'routers/%s' % router_id
        body ='{"name": "%s"}' % name
        return self._do_request(location, "PUT", body)

    # router port
    def create_router_port(self, router_id, network_address,\
                                            network_length, port_address,\
                                            local_network_address,\
                                            local_network_length):

        location = 'routers/%s/ports' % router_id

        data = {
            "networkAddress": network_address,
            "networkLength": network_length,
            "portAddress": port_address,
            "localNetworkAddress": local_network_address,
            "localNetworkLength" : local_network_length
            }
        body = json.dumps(data)
        return self._do_request(location, "POST", body)

    def link_router(self, router_id, network_address,\
                                       network_length, port_address,\
                                       peer_port_address,\
                                       peer_router_id):

        location = 'routers/%s/routers' % router_id

        data = {
            "networkAddress": network_address,
            "networkLength": network_length,
            "portAddress": port_address,
            "peerPortAddress": peer_port_address,
            "peerRouterId": peer_router_id
            }

        body = json.dumps(data)
        return self._do_request(location, "POST", body)


    def get_router_link(self, router_id, peer_router_id):
        location = 'routers/%s/link' % router_id
        body = '{"peerRouterId":"%s"}'% peer_router_id
        return self._do_request(location, "GET", body)

    def get_router_port(self, port_id):
        location = 'ports/%s' % port_id
        return self._do_request(location, "GET")

    def list_router_port(self, router_id):
        location = 'routers/%s/ports' % router_id
        return self._do_request(location, "GET")

    # vif
    def plug_vif(self, port_id, vif_id):
        location = 'ports/%s/plug' % port_id
        body = '{"vifId": "%s"}' % vif_id
        return self._do_request(location, "PUT", body)

    def unplug_vif(self, port_id, vif_id):
        location = 'ports/%s/unplug' % port_id
        body = '{"vifId": "%s"}' % vif_id
        return self._do_request(location, "PUT", body)

    # routes
    def create_route(self, router_id, src_network_addr, src_network_length,
                     type_, dst_network_addr, dst_network_length, next_hop_port,
                     next_hop_gateway, weight):

        location = 'routers/%s/routes' % router_id
        data = {"srcNetworkAddr": src_network_addr,
                "srcNetworkLength": src_network_length,
                "type": type_,
                "dstNetworkAddr": dst_network_addr,
                "dstNetworkLength": dst_network_length,
                "nextHopPort": next_hop_port,
                "nextHopGateway": next_hop_gateway,
                "weight": weight}

        body = json.dumps(data)
        return self._do_request(location, "POST", body)

    def get_route(self, routes_id):
        location = 'routes/%s' % routes_id
        return self._do_request(location, "GET", body)


    def list_route(self, router_id):
        location = 'routers/%s/routes' % router_id
        return self._do_request(location, "GET")

    # chains
    def create_chain(self, router_id, name):
        location = 'routers/%s/chains' % router_id
        body = '{"name": "%s"}' % name
        return self._do_request(location, "POST", body)

    def get_chain(self, chain_id):
        location = 'chains/%s' % chain_id
        return self._do_request(location, "GET")

    def list_chain(self, router_id):
        location = 'routers/%s/chains' % router_id
        return self._do_request(location, "GET")

    def update_chain(self, chain_id, name):
        location = 'routers/%s/chains' % router_id
        body = '{"name": "%s"}' % name
        return self._do_request(location, "PUT", body)

    # rules
    def create_rule(self, chain_id, 
                    cont_invert,
                    in_ports,
                    inv_in_ports,
                    out_ports,
                    inv_out_ports,
                    nw_tos,
                    inv_nw_tos,
                    nw_proto,
                    inv_nw_proto,
                    nw_src_address,
                    nw_src_length,
                    inv_nw_src,
                    nw_dst_address,
                    nw_dst_length,
                    inv_nw_dst,
                    tp_src_start,
                    tp_src_end,
                    inv_tp_src,
                    tp_dst_start,
                    tp_dst_end,
                    inv_tp_dst,
                    type_,
                    jump_chain_id,
                    jump_chain_name,
                    flow_action,
                    nat_targets, 
                    position ):

        location = 'chains/%s/rules' % chain_id
        
        data = {
            "condInvert": cont_invert,
            "inPorts": in_ports,
            "invInPorts": inv_in_ports,
            "outPorts": out_ports,
            "invOutPorts":inv_out_ports,
            "nwTos": nw_tos,
            "invNwTos": inv_nw_tos,
            "nwProto": nw_proto,
            "invNwProto": inv_nw_proto,
            "nwSrcAddress": nw_src_address,
            "nwSrcLength": nw_src_length,
            "invNwSrc":inv_nw_src,
            "nwDstAddress": nw_dst_address,
            "nwDstLength": nw_dst_length,
            "invNwDst": inv_nw_dst,
            "tpSrcStart": tp_src_start,
            "tpSrcEnd": tp_src_end,
            "invTpSrc": inv_tp_src,
            "tpDstStart": tp_dst_start,
            "tpDstEnd": tp_dst_end,
            "invTpDst": inv_tp_dst,
            "type": type_,
            "jumpChainId": jump_chain_id,
            "jumpChainName": jump_chain_name,
            "flowAction": flow_action,
            "natTargets": nat_targets, 
            "position": position
            }
        body = json.dumps(data)
        return self._do_request(location, "POST", body)

    def get_rule(self, rule_id):
        location = '/rules/%s' % chain_id
        return self._do_request(location, "GET")

    def list_rule(self, chain_id):
        location = 'chains/%s/rules' % chain_id
        return self._do_request(location, "GET")

    def delete(self, rule_id):
        location = '/rules/%s' % chain_id
        return self._do_request(location, "DELETE")

def main():
    def _process_arg(arg):
        if arg == "None":
            return None
        if all([c.isdigit() for c in arg]):
            return int(arg) # just assume int
        else:
            return arg

    client = MidonetClient(token = '999888777666')
    # simple repl.
    while True:
        try:
            input = raw_input('midonet_client> ')
            input = map(_process_arg, input.split())
            method_name, args = input[0], input[1:]
            method = getattr(client, method_name)
            r, c = method(*args)
            print "response: ", r
            print "content: ", c
        except Exception as e:
            print "Caught exeption: ", e


if __name__ == '__main__':
    sys.exit(main())
