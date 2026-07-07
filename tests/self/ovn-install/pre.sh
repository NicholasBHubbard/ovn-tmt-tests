#!/bin/bash
set -euo pipefail

source "$TMT_TREE/tests/lib/assert.sh"

for binary in ovn-nbctl ovn-sbctl ovn-northd ovn-controller; do
    assert_command_absent "$binary"
done

assert_finish
