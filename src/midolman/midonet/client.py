#!/usr/bin/env python


import sys
import httplib2
import readline


MIDONET_API_SERVER = 'http://localhost:8080'

class MidonetClient:

    def __init__(self, token):
        self.h = httplib2.Http()
        self.token = token

    def _do_request(self, location, method, body='{}'):

        url = MIDONET_API_SERVER + '/midolmanj-mgmt/v1/%s' % location
        print "-------------------"
        print "URL: ", url
        print "method: ", method
        print "body: ", body

        response, content = self.h.request(url, method, body, headers={
        "Content-Type": "application/json",
        "HTTP_X_AUTH_TOKEN": self.token} 
        )
        return response, content 

    def create_tenant(self, uuid=None):
        body = '{}'
        if uuid:
            body ='{"id": "%s"}' % uuid
            print body
    
        return self._do_request("tenants", "POST", body)

    # bridge
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


    # bridge port
    def create_port(self, bridge_id):
        assert bridge_id != None
        location = 'bridges/%s/ports' % bridge_id
        return self._do_request(location, "POST")

    def get_port(self, port_id):
        assert port_id != None
        location = 'ports/%s' % port_id
        return self._do_request(location, "GET")

    def list_port(self, bridge_id):
        assert bridge_id != None
        location = 'bridges/%s/ports' % bridge_id
        return self._do_request(location, "GET")

    def delete_port(self, port_id):
        assert port_id != None
        location = 'ports/%s' % port_id
        return self._do_request(location, "DELETE")


    # router
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







def main():

#    client = MidonetClient(token = '999888777666')
    #client = MidonetClient(token = '111222333444')
    client = MidonetClient(token = '2010')
#    r, c = b.create('c8854067-4c04-41d6-99cf-4e317e0999af', 'midobridge')

    while True:
        try:
            input = raw_input('midonet_client> ')
            input = input.split()
            method_name, args = input[0], input[1:]

            method = getattr(client, method_name)
            r, c = method(*args)
            print "response: ", r
            print "content: ", c
        except Exception as e:
            print "Caught exeption: ", e


if __name__ == '__main__':
    sys.exit(main())
