#!/bin/bash
set -euo pipefail

source "$TMT_TREE/tests/lib/multihost.sh"
multihost_run_playbook "$PWD/setup.yml"

case "$OVN_TEST_ENCAP" in
    geneve) system_interface=genev_sys_6081; expected_mtu=942 ;;
    vxlan) system_interface=vxlan_sys_4789; expected_mtu=950 ;;
    *) echo "Unsupported encapsulation: $OVN_TEST_ENCAP" >&2; exit 2 ;;
esac

compute_2_ip=$(multihost_guest_hostname compute-2)
route=$(multihost_exec compute-1 ip -4 route get "$compute_2_ip" | head -n 1)
route_device=$(awk '{for (i=1; i<=NF; i++) if ($i == "dev") print $(i+1)}' <<< "$route")
route_gateway=$(awk '{for (i=1; i<=NF; i++) if ($i == "via") print $(i+1)}' <<< "$route")

replace_underlay_mtu() {
    local mtu=$1

    if [ -n "$route_gateway" ]; then
        multihost_exec compute-1 ip route replace "$compute_2_ip/32" \
            via "$route_gateway" dev "$route_device" mtu "$mtu"
    else
        multihost_exec compute-1 ip route replace "$compute_2_ip/32" \
            dev "$route_device" mtu "$mtu"
    fi
}

reset_endpoint_routes() {
    multihost_ns_exec compute-1 pmtu-vm1 ip route flush dev pmtu-vm1
    multihost_ns_exec compute-1 pmtu-vm1 ip route add \
        10.70.0.0/24 dev pmtu-vm1
    multihost_ns_exec compute-1 pmtu-vm1 ip route add default \
        via 10.70.0.1 dev pmtu-vm1
}

restore_test_state() {
    multihost_exec compute-1 ip route del "$compute_2_ip/32" >/dev/null 2>&1 || true
    for guest in compute-1 compute-2 gateway-1; do
        multihost_exec "$guest" ovs-vsctl set open . \
            external-ids:ovn-encap-type=geneve >/dev/null 2>&1 || true
    done
}
trap restore_test_state EXIT

for guest in compute-1 compute-2 gateway-1; do
    multihost_exec "$guest" ovs-vsctl set open . \
        "external-ids:ovn-encap-type=$OVN_TEST_ENCAP"
done

for _ in {1..30}; do
    if multihost_exec compute-1 ip link show "$system_interface" >/dev/null 2>&1 && \
       multihost_exec compute-2 ip link show "$system_interface" >/dev/null 2>&1; then
        break
    fi
    sleep 1
done
multihost_exec compute-1 ip link show "$system_interface" >/dev/null
multihost_exec compute-2 ip link show "$system_interface" >/dev/null

reset_endpoint_routes
multihost_wait_for_ping compute-1 pmtu-vm1 10.70.0.4
replace_underlay_mtu 1200
output=$(multihost_ns_exec compute-1 pmtu-vm1 \
    ping -c 5 -s 1300 -M "do" 10.70.0.4 2>&1 || true)
if ! grep -qi 'message too long' <<< "$output"; then
    echo "Switching path did not report the reduced PMTU" >&2
    echo "$output" >&2
    exit 1
fi

reset_endpoint_routes
multihost_wait_for_ping compute-1 pmtu-vm1 20.70.0.3
replace_underlay_mtu 1100
output=$(multihost_ns_exec compute-1 pmtu-vm1 \
    ping -c 5 -s 1300 -M "do" 20.70.0.3 2>&1 || true)
if ! grep -qi 'message too long' <<< "$output"; then
    echo "Routed path did not report the reduced PMTU" >&2
    echo "$output" >&2
    exit 1
fi

reset_endpoint_routes
replace_underlay_mtu 1000
for _ in {1..30}; do
    multihost_ns_exec compute-1 pmtu-vm1 bash -c \
        'dd if=/dev/zero bs=1024 count=1 status=none > /dev/udp/10.70.0.1/8080' \
        >/dev/null 2>&1 || true
done
route=$(multihost_ns_exec compute-1 pmtu-vm1 \
    ip route get 10.70.0.1 dev pmtu-vm1)
if ! grep -q "mtu $expected_mtu" <<< "$route"; then
    echo "Expected learned PMTU $expected_mtu, found: $route" >&2
    exit 1
fi
