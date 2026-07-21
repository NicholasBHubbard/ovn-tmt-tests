#!/bin/bash
set -euo pipefail

source "$TMT_TREE/tests/lib/assert.sh"
source "$TMT_TREE/tests/lib/ovn.sh"

echo "Checking ovn-controller process..."
assert_process_present ovn-controller

echo "Checking br-int bridge exists..."
assert_ovs_bridge_present br-int
assert_ovs_bridge_present br-ex

echo "Checking OVS external-ids are configured..."
for key in ovn-remote ovn-encap-type ovn-encap-ip system-id; do
    assert_ovs_external_id_present "$key"
done

echo "Checking gateway configuration was cleared..."
for key in ovn-cms-options ovn-bridge-mappings; do
    assert_ovs_external_id_absent "$key"
done

echo "Checking chassis is registered in SB database..."
assert_ovn_chassis_present

assert_finish
