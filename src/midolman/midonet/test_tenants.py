#!/usr/bin/env python

import client
import sys
import unittest


class TestTenant(unittest.TestCase):
    
    def setUp(self):  # this also tests createing test without id
        token = "999888777666"
        self.mido_client = client.MidonetClient(token)
        r, c = self.mido_client.create_tenant()
        print r
        self.tenant_id  = r['location'].split('/')[-1]
        print self.tenant_id
        self.assertEquals(r['status'], '201')

    def test_create_tenant_with_id(self):
        import uuid
        id_ = uuid.uuid4()
        r, c = self.mido_client.create_tenant(id_)
        print r
        self.assertEquals(r['status'], '201')

    def test_create_tenant_with_existing_id(self): 
        r, c = self.mido_client.create_tenant(self.tenant_id)
        self.assertEquals(r['status'], '500')
     

if __name__ == '__main__':
    unittest.main()
