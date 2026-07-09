#!/bin/bash
set -euo pipefail

source "$TMT_TREE/tests/lib/assert.sh"

assert_path_absent /usr/local/dpdk
assert_finish
