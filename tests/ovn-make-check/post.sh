#!/bin/bash
set -euo pipefail

source "$TMT_TREE/tests/lib/assert.sh"

ovn_source_dir=${OVN_SOURCE_DIR:-/usr/src/ovn}
make_check_log=${MAKE_CHECK_LOG:-tests/testsuite.log}

assert_file "$ovn_source_dir/$make_check_log"

assert_finish
