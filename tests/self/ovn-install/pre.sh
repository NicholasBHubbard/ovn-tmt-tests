#!/bin/bash
set -euo pipefail

fail=0

assert_absent() {
    local binary=$1
    if command -v "$binary" >/dev/null 2>&1; then
        echo "Precondition failed: $binary is already installed at $(command -v "$binary")"
        fail=1
    fi
}

assert_absent ovn-nbctl
assert_absent ovn-sbctl
assert_absent ovn-northd
assert_absent ovn-controller

exit "$fail"
