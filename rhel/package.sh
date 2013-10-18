#!/bin/bash -e

SOURCES=~/rpmbuild/SOURCES
version=$1
package=python-midonet-openstack

mkdir -p $SOURCES
git archive HEAD --prefix=$package-$version/ -o $SOURCES/$package-$version.tar
gzip $SOURCES/$package-$version.tar
rpmbuild -ba rhel/python-midonet-openstack.spec
