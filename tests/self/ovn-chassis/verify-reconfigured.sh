#!/bin/bash
set -euo pipefail

source "$TMT_TREE/tests/lib/assert.sh"

if [ "$(ovs-vsctl get open . external-ids:ovn-cms-options | tr -d '"')" != \
    "enable-chassis-as-gw" ]; then
    record_failure "Expected replaced OVN CMS options"
fi
if [ "$(ovs-vsctl get open . external-ids:ovn-bridge-mappings | tr -d '"')" != \
    "provider:br-ex" ]; then
    record_failure "Expected replaced OVN bridge mapping"
fi

assert_finish
