#!/bin/bash
set -euo pipefail

source "$TMT_TREE/tests/lib/assert.sh"

assert_path_present /usr/local/dpdk
assert_path_present /usr/local/dpdk/lib64/pkgconfig/libdpdk.pc
assert_finish
