#!/bin/bash
set -euo pipefail

source "$TMT_TREE/tests/lib/assert.sh"

assert_file /usr/src/ovn/tests/testsuite.log

assert_finish
