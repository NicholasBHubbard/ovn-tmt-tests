#!/bin/bash
set -euo pipefail

source "$TMT_TREE/tests/lib/assert.sh"

if pip3 show scapy >/dev/null 2>&1; then
    record_failure "Precondition failed: scapy is already installed"
fi

assert_finish
