#!/usr/bin/env python

import client
import sys
import unittest


class TestBridge(unittest.TestCase):
    
    def setUp(self):  # this also tests createing bridge
        token = "999888777666"
        self.mido_client = client.MidonetClient(token)
        r, c = self.mido_client.create_tenant()
        print r
        self.tenant_id  = r['location'].split('/')[-1]
        print self.tenant_id
        self.assertEquals(r['status'], '201')


        name = "test_bridge_name"
        r, c = self.mido_client.create_bridge(self.tenant_id, name)
        self.bridge_id  = r['location'].split('/')[-1]
        print r
        self.assertEquals(r['status'], '201')

    def test_get(self):
    
        url = 'bridges/%s' % self.bridge_id 
        r, c = self.mido_client.get_bridge(self.bridge_id)
        print r
        self.assertEquals(r['status'], '200')


    def test_update(self):

        url = 'bridges/%s' % self.bridge_id 
        name = 'test_bridge_new_name'
        r, c = self.mido_client.update_bridge(self.bridge_id, name)
        print r
        self.assertEquals(r['status'], '200')
        print c
        

if __name__ == '__main__':
    unittest.main()
