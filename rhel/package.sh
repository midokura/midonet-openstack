#!/bin/bash -e

version=$1
package=python-midonet-openstack

git archive HEAD --prefix=$package-$version/ -o /home/midokura/rpmbuild/SOURCES/$package-$version.tar
gzip /home/midokura/rpmbuild/SOURCES/$package-$version.tar
rpmbuild -ba rhel/python-midonet-openstack.spec
