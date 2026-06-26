#!/bin/bash
set -euo pipefail

source "$(dirname "$0")/../../lib/assert.sh"
source "$(dirname "$0")/../../lib/ovn.sh"

assert_ovs_unconfigured
assert_process_absent ovs-vswitchd
assert_process_absent ovsdb-server
assert_finish
