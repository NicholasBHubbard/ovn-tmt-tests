#!/bin/bash
set -euo pipefail

source "$TMT_TREE/tests/lib/multihost.sh"
multihost_run_playbook "$PWD/setup.yml"

wait_for_mac_binding() {
    local address=$1

    for _ in {1..30}; do
        if ovn-sbctl --bare --columns=_uuid find Mac_Binding \
            "ip=\"$address\"" logical_port=na-public-router | grep -q .; then
            return 0
        fi
        sleep 1
    done

    echo "No MAC binding learned for $address" >&2
    return 1
}

ovn-sbctl --all destroy Mac_Binding

multihost_wait_for_ping compute-1 na-internal1 172.18.96.101
wait_for_mac_binding 172.18.96.101
multihost_wait_for_ping compute-1 na-internal1 172.18.96.102
wait_for_mac_binding 172.18.96.102
multihost_wait_for_ping compute-1 na-internal1 6812:96::101
wait_for_mac_binding 6812:96::101
multihost_wait_for_ping compute-1 na-internal1 6812:96::102
wait_for_mac_binding 6812:96::102

ovn-sbctl --all destroy Mac_Binding
multihost_exec compute-1 ip -n na-external1 -6 neigh flush dev na-external1
multihost_exec compute-2 ip -n na-external2 -6 neigh flush dev na-external2

multihost_wait_for_ping compute-1 na-external1 172.18.96.11
wait_for_mac_binding 172.18.96.101
multihost_wait_for_ping compute-2 na-external2 172.18.96.11
wait_for_mac_binding 172.18.96.102
multihost_wait_for_ping compute-1 na-external1 6812:96::11
wait_for_mac_binding 6812:96::101
multihost_wait_for_ping compute-2 na-external2 6812:96::11
wait_for_mac_binding 6812:96::102
