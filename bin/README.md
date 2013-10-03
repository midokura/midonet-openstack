# How to use setup_midonet_topology.py

### What is the provider router?

The provider router is the virtual router which provides internet connectivity
to the entire virtual topology.

It can be created with the setup_midonet_topology.py script. If using
OpenStack with MidoNet, it can also be created by just adding a router in Horizon;
see MidoNet install docs.


### Adding provider router
Example call to create a provider router:

```
python setup_midonet_topology.py MIDONET_API_URI ADMIN_USERNAME ADMIN_PASSWORD PROVIDER_TENANT_ID provider_devices
```

***Parameters:***

```MIDONET_API_URI```: MidoNet API URI, e.g. http://localhost:8080/midonet-api/

```ADMIN_USERNAME```, ```ADMIN_PASSWORD```: Username and password of the
MidoNet admin.

```PROVIDER_TENANT_ID```: tenant_id of the user who should own the provider
router device.

***Behavior:***

* Creates a provider router
* Once complete, displays the UUID of the newly created provider router

### Creating a fake uplink

Example call to create a fake uplink:

```
python setup_midonet_topology.py MIDONET_API_URI ADMIN_USERNAME ADMIN_PASSWORD PROVIDER_TENANT_ID setup_fake_uplink
```

***Parameters:***

As above.

***Behavior:***

* Gets the specified user's provider router
* Adds a new port (uplink port) on the provider router
    * Sets network 100.100.100.0/24 and port IP 100.100.100.1
* Sets a host-interface mapping for the new port
    * Mapped to the midonet interface on the current host, i.e. the machine on
    which the script is run
* Adds a default uplink route to send all traffic to 100.100.100.2 via the
uplink port