#!/bin/bash
set -euo pipefail

source "$TMT_TREE/tests/lib/assert.sh"
source "$TMT_TREE/tests/lib/ovn.sh"

assert_process_absent ovn-controller
assert_ovs_bridge_absent br-int

for key in ovn-remote ovn-encap-type ovn-encap-ip; do
    assert_ovs_external_id_absent "$key"
done

assert_finish
