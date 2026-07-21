#!/bin/bash
set -euo pipefail

source "$TMT_TREE/tests/lib/assert.sh"
source "$TMT_TREE/tests/lib/ovn.sh"

assert_ovs_bridge_present br-ex

if [ "$(ovs-vsctl get open . external-ids:ovn-cms-options | tr -d '"')" != \
    "enable-chassis-as-gw,prefer-chassis-as-gw" ]; then
    record_failure "Expected initial OVN CMS options"
fi
if [ "$(ovs-vsctl get open . external-ids:ovn-bridge-mappings | tr -d '"')" != \
    "public:br-ex" ]; then
    record_failure "Expected initial OVN bridge mapping"
fi

assert_finish
