#!/bin/bash
set -euo pipefail

source "$TMT_TREE/tests/lib/assert.sh"

assert_directory /usr/local/dpdk
assert_file /usr/local/dpdk/lib64/pkgconfig/libdpdk.pc
assert_finish
