#!/bin/bash
set -euo pipefail

mkdir -p /tmp/ovn-packages
dnf download --destdir=/tmp/ovn-packages \
    openvswitch ovn ovn-central ovn-host

echo "Downloaded packages:"
ls -1 /tmp/ovn-packages/
