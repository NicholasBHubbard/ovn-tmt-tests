#!/bin/bash
set -euo pipefail

source "$TMT_TREE/tests/lib/assert.sh"
source "$TMT_TREE/tests/lib/ovn.sh"

assert_process_absent ovn-controller
assert_ovs_bridge_absent br-int

for key in ovn-remote ovn-encap-type ovn-encap-ip; do
    assert_ovs_external_id_absent "$key"
done

for endpoint in self-vm1 self-vm2 self-remote self-delete; do
    if ip netns list | grep -q "^${endpoint}\\b"; then
        record_failure "Precondition failed: network namespace already exists: $endpoint"
    fi
    if ip link show "${endpoint}-p" >/dev/null 2>&1; then
        record_failure "Precondition failed: endpoint veth already exists: ${endpoint}-p"
    fi
done

assert_finish
