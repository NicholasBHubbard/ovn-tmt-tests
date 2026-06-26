#!/bin/bash
set -euo pipefail

source "$(dirname "$0")/../../lib/assert.sh"

for binary in ovs-vswitchd ovsdb-server ovn-nbctl ovn-sbctl ovn-northd ovn-controller; do
    assert_command_present "$binary"
    assert_command_runs "$binary --version" "$binary" --version
done

assert_finish
