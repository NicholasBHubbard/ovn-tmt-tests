#!/bin/bash
set -euo pipefail

fail=0

if command -v pgrep >/dev/null 2>&1; then
    if pgrep -x ovn-northd >/dev/null 2>&1; then
        echo "Precondition failed: ovn-northd is already running"
        fail=1
    fi
fi

if command -v ovn-nbctl >/dev/null 2>&1 && ovn-nbctl show >/dev/null 2>&1; then
    echo "Precondition failed: OVN northbound database is already accessible"
    fail=1
fi

if command -v ovn-sbctl >/dev/null 2>&1 && ovn-sbctl show >/dev/null 2>&1; then
    echo "Precondition failed: OVN southbound database is already accessible"
    fail=1
fi

exit "$fail"
