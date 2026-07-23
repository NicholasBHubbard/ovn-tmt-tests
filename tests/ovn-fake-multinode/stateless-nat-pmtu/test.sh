#!/bin/bash
set -euo pipefail

source "$TMT_TREE/tests/lib/multihost.sh"
multihost_run_playbook "$PWD/setup.yml"

multihost_wait_for_ping compute-1 snat-internal 172.19.1.2
multihost_ns_exec gateway-1 snat-router \
    ip link set dev snat-down mtu 1100

output=$(multihost_ns_exec compute-1 snat-internal \
    ping -c 20 -i 0.2 -s 1300 -M "do" 172.19.1.2 2>&1 || true)
if ! grep -q 'mtu = 1100' <<< "$output"; then
    echo "Stateless NAT did not preserve the ICMP PMTU signal" >&2
    echo "$output" >&2
    exit 1
fi
