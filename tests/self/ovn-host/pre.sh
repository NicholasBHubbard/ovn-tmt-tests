#!/bin/bash
set -euo pipefail

fail=0

if command -v pgrep >/dev/null 2>&1 && pgrep -x ovn-controller >/dev/null 2>&1; then
    echo "Precondition failed: ovn-controller is already running"
    fail=1
fi

if command -v ovs-vsctl >/dev/null 2>&1; then
    if ovs-vsctl br-exists br-int >/dev/null 2>&1; then
        echo "Precondition failed: br-int already exists"
        fail=1
    fi

    for key in ovn-remote ovn-encap-type ovn-encap-ip system-id; do
        if ovs-vsctl get open . "external-ids:$key" >/dev/null 2>&1; then
            echo "Precondition failed: OVS external-ids:$key is already configured"
            fail=1
        fi
    done
fi

exit "$fail"
