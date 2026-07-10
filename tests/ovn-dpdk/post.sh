#!/bin/bash
set -euo pipefail

source "$TMT_TREE/tests/lib/assert.sh"

ovn_source_dir=${OVN_SOURCE_DIR:-/usr/src/ovn}
ovs_vswitchd="$ovn_source_dir/ovs/vswitchd/ovs-vswitchd"

assert_executable "$ovs_vswitchd"

if [ -x "$ovs_vswitchd" ] && ! "$ovs_vswitchd" --version | grep -q '^DPDK '; then
    record_failure "Source-tree ovs-vswitchd does not have DPDK support"
fi

assert_finish
