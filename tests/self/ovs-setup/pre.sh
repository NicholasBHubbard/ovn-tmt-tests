#!/bin/bash
set -euo pipefail

fail=0

if command -v ovs-vsctl >/dev/null 2>&1 && ovs-vsctl show >/dev/null 2>&1; then
    echo "Precondition failed: OVS is already configured"
    fail=1
fi

if command -v pgrep >/dev/null 2>&1; then
    if pgrep -x ovs-vswitchd >/dev/null 2>&1; then
        echo "Precondition failed: ovs-vswitchd is already running"
        fail=1
    fi
    if pgrep -x ovsdb-server >/dev/null 2>&1; then
        echo "Precondition failed: ovsdb-server is already running"
        fail=1
    fi
fi

exit "$fail"
