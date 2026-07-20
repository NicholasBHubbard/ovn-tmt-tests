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
check_ovn_row() {
    local table=$1
    local name=$2
    local expected=$3
    local actual

    actual=$(ovn-nbctl --bare --columns=name find "$table" \
        name="$name" 2>/dev/null || true)
    if [ "$actual" != "$expected" ]; then
        record_failure "Expected $table $name result '$expected', found '$actual'"
    fi
}

check_ovn_row Logical_Switch self-sw self-sw
check_ovn_row Logical_Switch self-moved self-moved
check_ovn_row Logical_Switch self-unused ""

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

check_ovn_row Logical_Router self-r1 self-r1
check_ovn_row Logical_Router self-r2 ""
check_ovn_row Logical_Router self-r3 self-r3
check_router_option self-r1 chassis moved-chassis
check_router_option self-r1 mac_binding_age_threshold 10
if [ -n "$(ovn-nbctl --if-exists get Logical_Router self-r1 \
    options:dynamic_neigh_routers 2>/dev/null)" ]; then
    record_failure "Expected removed self-r1 option dynamic_neigh_routers to be absent"
fi
if [ "$(ovn-nbctl get Logical_Router self-r3 options 2>/dev/null || true)" != "{}" ]; then
    record_failure "Expected self-r3 to have no router options"
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
    local bridge=$4
    local mac=$5
    local actual_addresses actual_iface_id address expected_addresses
    shift 5

    check_logical_port "$iface_id" "$switch" "$mac" "$@"
    assert_command_runs "network namespace $name" ip netns exec "$name" true
    assert_command_runs "host interface ${name}-p" ip link show "${name}-p"

    if [ "$(ovs-vsctl port-to-br "${name}-p" 2>/dev/null)" != "$bridge" ]; then
        record_failure "Expected ${name}-p to be attached to $bridge"
    fi

    actual_iface_id=$(ovs-vsctl get Interface "${name}-p" \
        external_ids:iface-id 2>/dev/null | tr -d '"' || true)
    if [ "$actual_iface_id" != "$iface_id" ]; then
        record_failure "Expected $name iface-id $iface_id, found $actual_iface_id"
    fi

    if ! ip -n "$name" link show dev "$name" | grep -F -q "link/ether $mac"; then
        record_failure "Expected $name MAC address $mac"
    fi

    actual_addresses=$(ip -n "$name" -o address show dev "$name" \
        scope global | awk '{print $4}' | sort)
    expected_addresses=$(printf '%s\n' "$@" | sort)
    if [ "$actual_addresses" != "$expected_addresses" ]; then
        record_failure "Expected $name addresses '$expected_addresses', found '$actual_addresses'"
    fi
}

check_endpoint self-vm1 self-port1 self-moved self-br 02:00:00:00:01:02 \
    192.0.2.10/24 2001:db8:2::1/64
check_logical_port self-port2 self-moved 02:00:00:00:02:01 192.0.2.2/24
check_endpoint self-remote self-port3 self-moved self-br 02:00:00:00:03:02
check_ovn_row Logical_Switch_Port self-port4 ""

if [ "$(stat -Lc '%i' /var/run/netns/self-vm1)" != "$(</tmp/self-vm1-ns-id)" ]; then
    record_failure "Expected reapply to preserve the self-vm1 namespace"
fi
if [ "$(</sys/class/net/self-vm1-p/ifindex)" != "$(</tmp/self-vm1-ifindex)" ]; then
    record_failure "Expected reapply to preserve the self-vm1 veth"
fi

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

check_no_route() {
    local namespace=$1
    local family=$2
    local table=$3
    local destination=$4

    if ip -n "$namespace" "-$family" route show \
        table "$table" "$destination" 2>/dev/null | grep -q .; then
        record_failure "Expected route to be absent: $namespace table $table $destination"
    fi
}

check_route self-vm1 4 main default 192.0.2.1 ""
check_route self-vm1 4 101 203.0.113.0/24 192.0.2.2 ""
check_no_route self-vm1 4 100 198.51.100.0/24
check_no_route self-vm1 6 main default
check_no_route self-vm1 6 200 default

for endpoint in self-vm2 self-delete; do
    if ip netns list | grep -q "^${endpoint}\\b"; then
        record_failure "Expected endpoint namespace to be absent: $endpoint"
    fi
    if ip link show "${endpoint}-p" >/dev/null 2>&1; then
        record_failure "Expected endpoint veth to be absent: ${endpoint}-p"
    fi
done

assert_finish
