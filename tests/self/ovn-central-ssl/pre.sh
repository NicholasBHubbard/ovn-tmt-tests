#!/bin/bash
set -euo pipefail

source "$TMT_TREE/tests/lib/assert.sh"
source "$TMT_TREE/tests/lib/ovn.sh"

assert_process_absent ovn-northd
assert_ovn_nb_unavailable
assert_ovn_sb_unavailable
assert_finish
