#!/bin/bash
set -euo pipefail

source "$TMT_TREE/tests/lib/assert.sh"

assert_command_present automake
assert_command_present libtool

assert_finish
