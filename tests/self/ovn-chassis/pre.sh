#!/bin/bash
set -euo pipefail

source "$TMT_TREE/tests/lib/assert.sh"
source "$TMT_TREE/tests/lib/ovn.sh"

assert_process_absent ovn-controller
assert_ovs_bridge_absent br-int
assert_ovs_bridge_absent br-ex

for key in ovn-remote ovn-encap-type ovn-encap-ip ovn-cms-options \
    ovn-bridge-mappings; do
    assert_ovs_external_id_absent "$key"
done

assert_finish
