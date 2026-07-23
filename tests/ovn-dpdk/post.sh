#!/bin/bash
set -euo pipefail

source "$TMT_TREE/tests/lib/assert.sh"

source_dir=${OTT_SOURCE_DIR:-/usr/src/ovn}
ovs_vswitchd="$source_dir/ovs/vswitchd/ovs-vswitchd"

assert_executable "$ovs_vswitchd"

if [ -x "$ovs_vswitchd" ] && ! "$ovs_vswitchd" --version | grep -q '^DPDK '; then
    record_failure "Source-tree ovs-vswitchd does not have DPDK support"
fi

assert_finish
