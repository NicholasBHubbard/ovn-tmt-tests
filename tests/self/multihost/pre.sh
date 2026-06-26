#!/bin/bash
set -euo pipefail

source "$(dirname "$0")/../../lib/assert.sh"
source "$(dirname "$0")/../../lib/ovn.sh"

assert_process_absent ovn-northd
assert_process_absent ovn-controller
assert_ovn_sb_unavailable
assert_finish
