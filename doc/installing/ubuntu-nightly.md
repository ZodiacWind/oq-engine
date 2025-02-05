# Installing the OpenQuake Engine nightly builds on Ubuntu Linux

The OpenQuake Engine **nightly builds** are available in the form of *deb* binary packages for the following Ubuntu releases:
- **Ubuntu 16.04** LTS (Xenial)
- **Ubuntu 14.04** LTS (Trusty) 

Packages *may* work on Ubuntu derivatives (i.e. Mint Linux) and Debian, but this setup in not supported by GEM. See the [FAQ](../faq.md#unsupported-operating-systems)

The software and its libraries will be installed under `/opt/openquake`. Data will be stored under `/var/lib/openquake`.

## Install packages from the OpenQuake knightly repository

The following commands add the nightly builds package repository:
```bash
sudo add-apt-repository -ry ppa:openquake/ppa
sudo add-apt-repository -y ppa:openquake-automatic-team/latest-master
sudo apt-get update
```

Then to install the OpenQuake Engine and its libraries first remove stable packages and then install nightly build packages
```bash
sudo apt-get remove --purge python-oq-.*
sudo apt-get install python-oq-engine
```

Now you can follow the [standard installing procedures](./ubuntu.md#configure-the-system-services)

***

## Getting help
If you need help or have questions/comments/feedback for us, you can:
  * Subscribe to the OpenQuake users mailing list: https://groups.google.com/forum/?fromgroups#!forum/openquake-users
  * Contact us on IRC: irc.freenode.net, channel #openquake
