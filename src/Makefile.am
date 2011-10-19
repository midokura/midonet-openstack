# Copyright (C) 2011 Midokura KK

nobase_python_PYTHON = \
	midolman/__init__.py \
    midolman/nova/api/openstack/contrib/networks.py \
    midolman/nova/api/openstack/contrib/__init__.py \
    midolman/nova/network/api.py \
    midolman/nova/network/manager.py \
    midolman/nova/network/__init__.py \
    midolman/nova/virt/libvirt/libvirt.xml.template \
    midolman/nova/virt/libvirt/connection.py


# Distribute but don't install docs, etc.
dist_noinst_DATA =

# Distribute but don't install unittests.
UNITTESTS = 

noinst_PYTHON = \
	$(UNITTESTS)

# Instead of running every unittest module by setting
# TESTS = $(UNITTESTS), run them all as a single test suite.
TESTS = test_all.py
CLEANFILES = test_all.py midolman/*.c
EXTRADIST = test_all.py.in
test_all.py: test_all.py.in $(UNITTESTS)
	@echo generating test suite $@
	@unittest_files="$(UNITTESTS)"; modules=;\
	for file in $$unittest_files; do\
	  module=`echo $$file | sed -e 's/\.py$$//' -e 'y/\//./'`;\
	  modules="$$modules '$$module',"; done;\
	sed -e 's/@UNITTEST_MODULES@/['"$$modules"']/'\
	  $(srcdir)/test_all.py.in > $@

# The command to run the test_all.py unittests.
TESTS_ENVIRONMENT = PYTHONPATH=$(srcdir):$(builddir) $(PYTHON) -B
