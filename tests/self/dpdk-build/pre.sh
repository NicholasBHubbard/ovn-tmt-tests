#!/bin/bash
set -euo pipefail

source "$TMT_TREE/tests/lib/assert.sh"

if [ -d /usr/local/dpdk ]; then
    record_failure "Precondition failed: /usr/local/dpdk already exists"
fi
assert_finish
