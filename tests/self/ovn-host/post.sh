#!/bin/bash
set -euo pipefail

source "$TMT_TREE/tests/lib/assert.sh"
source "$TMT_TREE/tests/lib/ovn.sh"

echo "Checking ovn-controller process..."
assert_process_present ovn-controller

echo "Checking br-int bridge exists..."
assert_ovs_bridge_present br-int

echo "Checking OVS external-ids are configured..."
for key in ovn-remote ovn-encap-type ovn-encap-ip system-id; do
    assert_ovs_external_id_present "$key"
done

echo "Checking chassis is registered in SB database..."
assert_ovn_chassis_present

echo "Checking namespace endpoints..."
check_logical_switch() {
    local switch=$1
    local actual

    actual=$(ovn-nbctl --bare --columns=name find Logical_Switch \
        name="$switch" 2>/dev/null || true)
    if [ "$actual" != "$switch" ]; then
        record_failure "Expected logical switch to exist: $switch"
    fi
}

check_logical_switch self-sw
check_logical_switch self-unused

check_logical_router() {
    local router=$1
    local actual

    actual=$(ovn-nbctl --bare --columns=name find Logical_Router \
        name="$router" 2>/dev/null || true)
    if [ "$actual" != "$router" ]; then
        record_failure "Expected logical router to exist: $router"
    fi
}

check_router_option() {
    local router=$1
    local option=$2
    local expected=$3
    local actual

    actual=$(ovn-nbctl get Logical_Router "$router" \
        "options:$option" 2>/dev/null | tr -d '"' || true)
    if [ "$actual" != "$expected" ]; then
        record_failure "Expected $router option $option=$expected, found $actual"
    fi
}

check_logical_router self-r1
check_logical_router self-r2
check_router_option self-r1 chassis self-chassis
check_router_option self-r1 dynamic_neigh_routers true
check_router_option self-r1 mac_binding_age_threshold 5

if [ "$(ovn-nbctl get Logical_Router self-r2 options 2>/dev/null || true)" != "{}" ]; then
    record_failure "Expected self-r2 to have no router options"
fi

check_logical_port() {
    local iface_id=$1
    local switch=$2
    local mac=$3
    local expected_nb_addresses=$mac
    local actual_nb_addresses actual_switch address expected_switch
    shift 3

    expected_switch=$(ovn-nbctl --bare --columns=_uuid find Logical_Switch \
        name="$switch" 2>/dev/null || true)
    actual_switch=$(ovn-nbctl lsp-get-ls "$iface_id" 2>/dev/null || true)
    actual_switch=${actual_switch%% *}
    if [ "$actual_switch" != "$expected_switch" ]; then
        record_failure "Expected $iface_id on $switch, found $actual_switch"
    fi

    for address in "$@"; do
        expected_nb_addresses+=" ${address%/*}"
    done

    actual_nb_addresses=$(ovn-nbctl lsp-get-addresses "$iface_id" \
        2>/dev/null | tr -d '"' || true)
    if [ "$actual_nb_addresses" != "$expected_nb_addresses" ]; then
        record_failure "Expected $iface_id addresses $expected_nb_addresses, found $actual_nb_addresses"
    fi
}

check_endpoint() {
    local name=$1
    local iface_id=$2
    local switch=$3
    local mac=$4
    local actual_iface_id address
    shift 4

    check_logical_port "$iface_id" "$switch" "$mac" "$@"
    assert_command_runs "network namespace $name" ip netns exec "$name" true
    assert_command_runs "host interface ${name}-p" ip link show "${name}-p"

    if [ "$(ovs-vsctl port-to-br "${name}-p" 2>/dev/null)" != br-int ]; then
        record_failure "Expected ${name}-p to be attached to br-int"
    fi

    actual_iface_id=$(ovs-vsctl get Interface "${name}-p" \
        external_ids:iface-id 2>/dev/null | tr -d '"' || true)
    if [ "$actual_iface_id" != "$iface_id" ]; then
        record_failure "Expected $name iface-id $iface_id, found $actual_iface_id"
    fi

    if ! ip -n "$name" link show dev "$name" | grep -F -q "link/ether $mac"; then
        record_failure "Expected $name MAC address $mac"
    fi

    for address in "$@"; do
        if ! ip -n "$name" -o address show dev "$name" | grep -F -q "$address"; then
            record_failure "Expected $name address $address"
        fi
    done
}

check_endpoint self-vm1 self-port1 self-sw 02:00:00:00:01:01 \
    192.0.2.1/24 192.0.2.11/24 2001:db8:1::1/64
check_endpoint self-vm2 self-port2 self-sw 02:00:00:00:02:01 \
    192.0.2.2/24
check_logical_port self-port3 self-sw 02:00:00:00:03:01 192.0.2.3/24

check_route() {
    local namespace=$1
    local family=$2
    local table=$3
    local destination=$4
    local via=$5
    local metric=$6
    local actual expected=$destination

    actual=$(ip -n "$namespace" "-$family" route show \
        table "$table" "$destination" 2>/dev/null || true)
    if [ -n "$via" ]; then
        expected+=" via $via"
    fi
    expected+=" dev $namespace"
    if [ -n "$metric" ]; then
        expected+=" metric $metric"
    fi

    if [[ "$actual" != "$expected"* ]]; then
        record_failure "Expected route '$expected', found '$actual'"
    fi
}

check_route self-vm1 4 main default 192.0.2.254 ""
check_route self-vm1 4 100 198.51.100.0/24 192.0.2.253 100
check_route self-vm1 6 main default 2001:db8:1::ff 50
check_route self-vm1 6 200 default "" ""

if ip -n self-vm2 -4 route show default | grep -q .; then
    record_failure "Unexpected default route on endpoint without routes: self-vm2"
fi

if ip netns list | grep -q '^self-remote\b'; then
    record_failure "Unexpected endpoint namespace on this host: self-remote"
fi
if ip link show self-remote-p >/dev/null 2>&1; then
    record_failure "Unexpected endpoint veth on this host: self-remote-p"
fi

assert_finish
