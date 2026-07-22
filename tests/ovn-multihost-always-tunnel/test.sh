#!/bin/bash
set -euo pipefail

source "$TMT_TREE/tests/lib/multihost.sh"
multihost_run_playbook "$PWD/setup.yml"

run_traffic() {
    multihost_ns_exec compute-1 at-vm1 ping -q -c 3 -W 2 10.60.0.4
    multihost_ns_exec compute-1 at-vm1 ping -q -c 3 -W 2 20.60.0.3
}

assert_tunnel_destination() {
    local expected_ip=$1
    local destination_mac=$2
    local destination_ip=$3
    local trace

    trace=$(multihost_exec compute-1 ovs-appctl ofproto/trace br-int \
        "in_port=at-vm1-p,icmp,dl_src=02:00:00:60:10:03,dl_dst=$destination_mac,nw_src=10.60.0.3,nw_dst=$destination_ip,nw_ttl=64,icmp_type=8,icmp_code=0")
    if ! grep -Fq "dst=$expected_ip,ttl=" <<< "$trace"; then
        echo "Traffic to $destination_ip did not use tunnel destination $expected_ip" >&2
        echo "$trace" >&2
        exit 1
    fi
}

assert_paths() {
    local tunnel_destination=$1

    run_traffic
    assert_tunnel_destination "$tunnel_destination" \
        02:00:00:60:10:04 10.60.0.4
    assert_tunnel_destination "$tunnel_destination" \
        02:00:00:60:00:01 20.60.0.3
}

compute_2_ip=$(multihost_guest_hostname compute-2)
provider_hub_ip=$(multihost_guest_hostname gateway-1)

reset_always_tunnel() {
    ovn-nbctl remove NB_Global . options always_tunnel >/dev/null 2>&1 || true
}
trap reset_always_tunnel EXIT

reset_always_tunnel
ovn-nbctl --wait=hv sync
assert_paths "$provider_hub_ip"

ovn-nbctl set NB_Global . options:always_tunnel=true
ovn-nbctl --wait=hv sync
assert_paths "$compute_2_ip"
