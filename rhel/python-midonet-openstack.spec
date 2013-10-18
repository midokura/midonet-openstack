Name:       python-midonet-openstack
Epoch:      1
Version:    2013.2.0_0
Release:    0
Summary:    OpenStack plugin for MidoNet.
Group:      Development/Languages
License:    Test
URL:        https://github.com/midokura/midonet-openstack
Source0:    https://github.com/midokura/midonet-openstack/python-midonet-openstack-%{version}.tar.gz
BuildArch:  noarch
BuildRoot:  /var/tmp/%{name}-buildroot

%description
OpenStack plugin for MidoNet

%prep
%setup -q

%install
mkdir -p $RPM_BUILD_ROOT/%{python_sitelib}
cp -r src/midonet $RPM_BUILD_ROOT/%{python_sitelib}/

%files
%defattr(-,root,root)
%{python_sitelib}/midonet

%changelog
* Sat Oct 18 2013 Dave Cahill <dcahill@midokura.com> - 2013.2.0_0
- Initial Havana package
