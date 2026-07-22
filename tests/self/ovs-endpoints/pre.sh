#!/bin/bash
set -euo pipefail

source "$TMT_TREE/tests/lib/assert.sh"
source "$TMT_TREE/tests/lib/ovn.sh"

for bridge in self-br-a self-br-b; do
    assert_ovs_bridge_absent "$bridge"
done

for endpoint in self-direct self-peer self-delete self-away self-stale self-keep \
    self-long-endpoint-name; do
    if ip netns list | grep -q "^${endpoint}\\b"; then
        record_failure "Precondition failed: namespace exists: $endpoint"
    fi
    if ip link show "${endpoint}-p" >/dev/null 2>&1; then
        record_failure "Precondition failed: interface exists: ${endpoint}-p"
    fi
done

long_host_interface="ovse-$(printf %s self-long-endpoint-name | sha1sum | cut -c1-10)"
if ip link show "$long_host_interface" >/dev/null 2>&1; then
    record_failure "Precondition failed: interface exists: $long_host_interface"
fi

assert_finish
