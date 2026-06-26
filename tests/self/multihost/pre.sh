#!/bin/bash
set -euo pipefail

fail=0

if command -v pgrep >/dev/null 2>&1; then
    for process in ovn-northd ovn-controller; do
        if pgrep -x "$process" >/dev/null 2>&1; then
            echo "Precondition failed: $process is already running"
            fail=1
        fi
    done
fi

if command -v ovn-sbctl >/dev/null 2>&1 && ovn-sbctl show >/dev/null 2>&1; then
    echo "Precondition failed: OVN southbound database is already accessible"
    fail=1
fi

exit "$fail"
