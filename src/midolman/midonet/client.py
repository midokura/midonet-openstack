#!/usr/bin/env python


import sys
import httplib2
import readline


class MidonetClient:

    def __init__(self, token):
        self.h = httplib2.Http()
        self.token = token
        pass

    def _do_request(self, location, method, body='{}'):

        url = 'http://localhost:8080/midolmanj-mgmt/v1/%s' % location
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




def main():

    client = MidonetClient(token = '999888777666')
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
