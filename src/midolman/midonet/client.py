#!/usr/bin/env python


import sys
import httplib2


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


def main():

    client = MidonetClient(token = '999888777666')
#    r, c = b.create('c8854067-4c04-41d6-99cf-4e317e0999af', 'midobridge')
    r, c = client.get_bridge('317df47a-bd68-4a97-a617-160f73aa3127')

    print "response: ", r
    print "contents: ", c

    r, c = client.update_bridge('317df47a-bd68-4a97-a617-160f73aa3127', "shika")

    print "response: ", r
    print "contents: ", c

if __name__ == '__main__':
    sys.exit(main())
