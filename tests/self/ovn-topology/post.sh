#!/bin/bash
set -euo pipefail

source "$TMT_TREE/tests/lib/assert.sh"
source "$TMT_TREE/tests/lib/ovn.sh"

echo "Checking OVN topology..."
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
if [ "$(ovn-nbctl get Logical_Switch self-moved other_config:subnet | tr -d '\"')" != \
    198.51.100.0/24 ]; then
    record_failure "Expected self-moved other_config subnet to be replaced"
fi
if [ "$(ovn-nbctl get Logical_Switch self-moved other_config:mcast_snoop | tr -d '\"')" != \
    false ]; then
    record_failure "Expected self-moved other_config mcast_snoop to be replaced"
fi
if [ -n "$(ovn-nbctl --if-exists get Logical_Switch self-moved \
    other_config:exclude_ips 2>/dev/null)" ]; then
    record_failure "Expected omitted self-moved other_config exclude_ips to be absent"
fi
if [ "$(ovn-nbctl get Logical_Switch self-sw other_config:subnet | tr -d '\"')" != \
    192.0.2.0/24 ]; then
    record_failure "Expected unlisted self-sw other_config subnet to remain"
fi
if [ "$(ovn-nbctl get Logical_Switch self-sw other_config:exclude_ips | tr -d '\"')" != \
    192.0.2.1..192.0.2.2 ]; then
    record_failure "Expected unlisted self-sw other_config exclude_ips to remain"
fi
if [ "$(</tmp/self-moved-id)" != "$(ovn-nbctl --bare --columns=_uuid find \
    Logical_Switch name=self-moved)" ]; then
    record_failure "Expected logical switch identity to survive reconfiguration and reapply"
fi

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

check_router_attachment() {
    local router_port=$1
    local switch_port=$2
    local router=$3
    local switch=$4
    local mac=$5
    local actual_mac actual_networks actual_router actual_switch
    local expected_networks router_port_uuid switch_port_uuid
    shift 5

    router_port_uuid=$(ovn-nbctl --bare --columns=_uuid find \
        Logical_Router_Port name="$router_port" 2>/dev/null || true)
    switch_port_uuid=$(ovn-nbctl --bare --columns=_uuid find \
        Logical_Switch_Port name="$switch_port" 2>/dev/null || true)
    if [ -z "$router_port_uuid" ] || [ -z "$switch_port_uuid" ]; then
        record_failure "Expected router attachment $router_port/$switch_port"
        return
    fi

    actual_router=$(ovn-nbctl --bare --columns=name find Logical_Router \
        "ports{>=}$router_port_uuid" 2>/dev/null || true)
    actual_switch=$(ovn-nbctl --bare --columns=name find Logical_Switch \
        "ports{>=}$switch_port_uuid" 2>/dev/null || true)
    if [ "$actual_router" != "$router" ]; then
        record_failure "Expected $router_port on $router, found $actual_router"
    fi
    if [ "$actual_switch" != "$switch" ]; then
        record_failure "Expected $switch_port on $switch, found $actual_switch"
    fi

    actual_mac=$(ovn-nbctl get Logical_Router_Port "$router_port" mac \
        2>/dev/null | tr -d '"' || true)
    if [ "$actual_mac" != "$mac" ]; then
        record_failure "Expected $router_port MAC $mac, found $actual_mac"
    fi

    actual_networks=$(ovn-nbctl get Logical_Router_Port "$router_port" networks \
        2>/dev/null | tr -d '[],"' | tr ' ' '\n' | sed '/^$/d' | sort)
    expected_networks=$(printf '%s\n' "$@" | sort)
    if [ "$actual_networks" != "$expected_networks" ]; then
        record_failure "Expected $router_port networks '$expected_networks', found '$actual_networks'"
    fi

    if [ "$(ovn-nbctl get Logical_Switch_Port "$switch_port" type \
        2>/dev/null | tr -d '"' || true)" != "router" ]; then
        record_failure "Expected $switch_port type router"
    fi
    if [ "$(ovn-nbctl get Logical_Switch_Port "$switch_port" \
        options:router-port 2>/dev/null | tr -d '"' || true)" != "$router_port" ]; then
        record_failure "Expected $switch_port to reference $router_port"
    fi
    if [ "$(ovn-nbctl get Logical_Switch_Port "$switch_port" addresses \
        2>/dev/null | tr -d '[]," ' || true)" != "router" ]; then
        record_failure "Expected $switch_port addresses router"
    fi
}

check_router_attachment self-rp self-rp-sw self-r3 self-moved \
    02:00:00:00:10:03 203.0.113.1/24 2001:db8:2::ff/64
if [ "$(ovn-nbctl get Logical_Router_Port self-rp options:gateway_mtu \
    2>/dev/null | tr -d '\"' || true)" != 1300 ]; then
    record_failure "Expected self-rp option gateway_mtu=1300"
fi
if [ -n "$(ovn-nbctl --if-exists get Logical_Router_Port self-rp \
    options:redirect-type 2>/dev/null)" ]; then
    record_failure "Expected omitted self-rp option redirect-type to be absent"
fi
check_ovn_row Logical_Router_Port self-rp-delete ""
check_ovn_row Logical_Switch_Port self-rp-delete-sw ""

if [ "$(</tmp/self-rp-id)" != "$(ovn-nbctl --bare --columns=_uuid find \
    Logical_Router_Port name=self-rp)" ]; then
    record_failure "Expected router port identity to survive reconfiguration"
fi
if [ "$(</tmp/self-rp-sw-id)" != "$(ovn-nbctl --bare --columns=_uuid find \
    Logical_Switch_Port name=self-rp-sw)" ]; then
    record_failure "Expected router switch port identity to survive reconfiguration"
fi

check_localnet_port() {
    local name=$1
    local switch=$2
    local network=$3
    local tag=$4
    local actual port_uuid

    port_uuid=$(ovn-nbctl --bare --columns=_uuid find \
        Logical_Switch_Port name="$name" 2>/dev/null || true)
    if [ -z "$port_uuid" ]; then
        record_failure "Expected localnet port $name"
        return
    fi

    actual=$(ovn-nbctl --bare --columns=name find Logical_Switch \
        "ports{>=}$port_uuid" 2>/dev/null || true)
    if [ "$actual" != "$switch" ]; then
        record_failure "Expected localnet port $name on $switch, found $actual"
    fi
    if [ "$(ovn-nbctl get Logical_Switch_Port "$name" type | tr -d '\"')" != \
        "localnet" ]; then
        record_failure "Expected $name type localnet"
    fi

    actual=$(ovn-nbctl get Logical_Switch_Port "$name" \
        options:network_name 2>/dev/null | tr -d '\"' || true)
    if [ "$actual" != "$network" ]; then
        record_failure "Expected localnet port $name network $network, found $actual"
    fi
    if [ "$(ovn-nbctl lsp-get-addresses "$name" | tr -d '\"')" != "unknown" ]; then
        record_failure "Expected localnet port $name addresses unknown"
    fi

    actual=$(ovn-nbctl lsp-get-tag "$name" 2>/dev/null || true)
    if [ "$actual" != "$tag" ]; then
        record_failure "Expected localnet port $name tag $tag, found $actual"
    fi
}

check_localnet_port self-localnet self-moved self-provider-moved ""
check_ovn_row Logical_Switch_Port self-localnet-delete ""
check_ovn_row Logical_Switch_Port self-localnet-unmanaged self-localnet-unmanaged
localnet_port_id=$(ovn-nbctl --bare --columns=_uuid find \
    Logical_Switch_Port name=self-localnet)
if [ "$(</tmp/self-localnet-id)" != "$localnet_port_id" ] || \
    [ "$(</tmp/self-localnet-moved-id)" != "$localnet_port_id" ]; then
    record_failure "Expected localnet port identity to survive reconfiguration and reapply"
fi

check_gateway_chassis() {
    local id=$1
    local router_port=$2
    local chassis=$3
    local priority=$4
    local actual gateway_uuid

    gateway_uuid=$(ovn-nbctl --bare --columns=_uuid find \
        Gateway_Chassis name="$id" 2>/dev/null || true)
    if [ -z "$gateway_uuid" ]; then
        record_failure "Expected gateway chassis assignment $id"
        return
    fi

    actual=$(ovn-nbctl --bare --columns=name find Logical_Router_Port \
        "gateway_chassis{>=}$gateway_uuid" 2>/dev/null || true)
    if [ "$actual" != "$router_port" ]; then
        record_failure "Expected gateway chassis $id on $router_port, found $actual"
    fi
    actual=$(ovn-nbctl get Gateway_Chassis "$gateway_uuid" chassis_name \
        2>/dev/null | tr -d '\"' || true)
    if [ "$actual" != "$chassis" ]; then
        record_failure "Expected gateway chassis $id chassis $chassis, found $actual"
    fi
    actual=$(ovn-nbctl get Gateway_Chassis "$gateway_uuid" priority \
        2>/dev/null || true)
    if [ "$actual" != "$priority" ]; then
        record_failure "Expected gateway chassis $id priority $priority, found $actual"
    fi
}

check_gateway_chassis self-gateway self-rp self-gateway-2 30
check_gateway_chassis self-gateway-secondary self-rp self-gateway-backup 10
check_ovn_row Gateway_Chassis self-gateway-delete ""
unmanaged_gateway_id=$(ovn-nbctl --bare --columns=_uuid find \
    Gateway_Chassis chassis_name=self-gateway-unmanaged)
if [ -z "$unmanaged_gateway_id" ] || \
    [ "$(ovn-nbctl --bare --columns=name find Logical_Router_Port \
        "gateway_chassis{>=}$unmanaged_gateway_id")" != "self-rp-gateway" ]; then
    record_failure "Expected unmanaged gateway chassis assignment to remain"
fi
gateway_chassis_id=$(ovn-nbctl --bare --columns=_uuid find \
    Gateway_Chassis name=self-gateway)
if [ "$(</tmp/self-gateway-id)" != "$gateway_chassis_id" ] || \
    [ "$(</tmp/self-gateway-moved-id)" != "$gateway_chassis_id" ]; then
    record_failure "Expected gateway chassis identity to survive reconfiguration and reapply"
fi

check_dhcp_option() {
    local id=$1
    local option=$2
    local expected=$3
    local row=$4
    local actual

    actual=$(ovn-nbctl --if-exists get DHCP_Options "$row" \
        "options:$option" 2>/dev/null | tr -d '"' || true)
    if [ "$actual" != "$expected" ]; then
        record_failure "Expected DHCP options $id $option=$expected, found $actual"
    fi
}

dhcp_uuid=$(ovn-nbctl --bare --columns=_uuid find DHCP_Options \
    external_ids:ovn-tmt-tests-id=self-dhcp)
if [ -z "$dhcp_uuid" ]; then
    record_failure "Expected managed DHCP options self-dhcp"
else
    if [ "$(ovn-nbctl get DHCP_Options "$dhcp_uuid" cidr | tr -d '"')" != \
        198.51.100.0/24 ]; then
        record_failure "Expected DHCP options self-dhcp CIDR 198.51.100.0/24"
    fi
    check_dhcp_option self-dhcp server_id 198.51.100.1 "$dhcp_uuid"
    check_dhcp_option self-dhcp lease_time 7200 "$dhcp_uuid"
    check_dhcp_option self-dhcp dns_server 198.51.100.53 "$dhcp_uuid"
    check_dhcp_option self-dhcp ip_forward_enable 1 "$dhcp_uuid"
    check_dhcp_option self-dhcp classless_static_route \
        "{0.0.0.0/0, 198.51.100.1}" "$dhcp_uuid"
    check_dhcp_option self-dhcp server_mac "" "$dhcp_uuid"
    check_dhcp_option self-dhcp router "" "$dhcp_uuid"
    if [ "$(</tmp/self-dhcp-id)" != "$dhcp_uuid" ] || \
        [ "$(</tmp/self-dhcp-moved-id)" != "$dhcp_uuid" ]; then
        record_failure "Expected DHCP options identity to survive reconfiguration and reapply"
    fi
fi
if ovn-nbctl --bare --columns=_uuid find DHCP_Options \
    external_ids:ovn-tmt-tests-id=self-dhcp-delete | grep -q .; then
    record_failure "Expected deleted managed DHCP options to be absent"
fi
dhcp_v6_uuid=$(ovn-nbctl --bare --columns=_uuid find DHCP_Options \
    external_ids:ovn-tmt-tests-id=self-dhcp-v6)
if [ "$dhcp_v6_uuid" != "$(</tmp/self-dhcp-v6-id)" ]; then
    record_failure "Expected unlisted managed DHCP options to remain"
else
    if [ "$(ovn-nbctl get DHCP_Options "$dhcp_v6_uuid" cidr | tr -d '"')" != \
        2001:db8:1::/64 ]; then
        record_failure "Expected unlisted DHCP options CIDR 2001:db8:1::/64"
    fi
    check_dhcp_option self-dhcp-v6 server_id 02:00:00:00:10:01 "$dhcp_v6_uuid"
    check_dhcp_option self-dhcp-v6 dns_server 2001:db8::53 "$dhcp_v6_uuid"
fi
if ! ovn-nbctl --bare --columns=_uuid find DHCP_Options \
    cidr=10.10.0.0/24 | grep -q .; then
    record_failure "Expected unmanaged DHCP options to remain"
fi

check_nat_field() {
    local id=$1
    local field=$2
    local expected=$3
    local nat_uuid=$4
    local actual

    actual=$(ovn-nbctl get NAT "$nat_uuid" "$field" 2>/dev/null | \
        tr -d '[]"' || true)
    if [ "$actual" != "$expected" ]; then
        record_failure "Expected NAT rule $id $field=$expected, found $actual"
    fi
}

nat_uuid=$(ovn-nbctl --bare --columns=_uuid find NAT \
    external_ids:ovn-tmt-tests-id=self-nat)
if [ -z "$nat_uuid" ]; then
    record_failure "Expected managed NAT rule self-nat"
else
    check_nat_field self-nat type dnat "$nat_uuid"
    check_nat_field self-nat external_ip 2001:db8:ffff::10 "$nat_uuid"
    check_nat_field self-nat logical_ip 2001:db8:2::1 "$nat_uuid"
    for field in logical_port external_mac external_port_range gateway_port match; do
        check_nat_field self-nat "$field" "" "$nat_uuid"
    done
    check_nat_field self-nat options "{}" "$nat_uuid"
    check_nat_field self-nat priority 0 "$nat_uuid"
    if [ "$(ovn-nbctl --bare --columns=name find Logical_Router \
        "nat{>=}$nat_uuid")" != self-r3 ]; then
        record_failure "Expected NAT rule self-nat on self-r3"
    fi
    if [ "$(</tmp/self-nat-id)" != "$nat_uuid" ] || \
        [ "$(</tmp/self-nat-moved-id)" != "$nat_uuid" ]; then
        record_failure "Expected NAT rule identity to survive reconfiguration and reapply"
    fi
fi
if ovn-nbctl --bare --columns=_uuid find NAT \
    external_ids:ovn-tmt-tests-id=self-nat-delete | grep -q .; then
    record_failure "Expected deleted managed NAT rule to be absent"
fi
unlisted_nat_uuid=$(ovn-nbctl --bare --columns=_uuid find NAT \
    external_ids:ovn-tmt-tests-id=self-nat-snat)
if [ "$unlisted_nat_uuid" != "$(</tmp/self-nat-snat-id)" ]; then
    record_failure "Expected unlisted managed NAT rule to remain"
else
    check_nat_field self-nat-snat type snat "$unlisted_nat_uuid"
    check_nat_field self-nat-snat external_ip 198.51.100.20 "$unlisted_nat_uuid"
    check_nat_field self-nat-snat logical_ip 192.0.2.0/24 "$unlisted_nat_uuid"
    if [ "$(ovn-nbctl --bare --columns=name find Logical_Router \
        "nat{>=}$unlisted_nat_uuid")" != self-r1 ]; then
        record_failure "Expected unlisted NAT rule self-nat-snat on self-r1"
    fi
fi
if ! ovn-nbctl lr-nat-list self-r3 | grep -F -q '203.0.113.20'; then
    record_failure "Expected unmanaged NAT rule to remain"
fi

load_balancer_uuid=$(ovn-nbctl --bare --columns=_uuid find Load_Balancer \
    external_ids:ovn-tmt-tests-id=self-lb)
if [ -z "$load_balancer_uuid" ]; then
    record_failure "Expected managed load balancer self-lb"
else
    if [ "$load_balancer_uuid" != "$(</tmp/self-lb-id)" ]; then
        record_failure "Expected load balancer identity to survive reconfiguration"
    fi
    if [ "$(ovn-nbctl get Load_Balancer "$load_balancer_uuid" protocol \
        | tr -d '\"')" != tcp ]; then
        record_failure "Expected self-lb protocol tcp"
    fi
    if [ "$(ovn-nbctl get Load_Balancer "$load_balancer_uuid" \
        'vips:"198.51.100.100:443"' | tr -d '\"')" != \
        198.51.100.10:8443 ]; then
        record_failure "Expected self-lb replacement VIP"
    fi
    if [ "$(ovn-nbctl get Load_Balancer "$load_balancer_uuid" vips \
        | grep -o ':443' | wc -l)" -ne 1 ]; then
        record_failure "Expected omitted self-lb VIPs to be absent"
    fi
    if [ "$(ovn-nbctl get Load_Balancer "$load_balancer_uuid" options:reject \
        | tr -d '\"')" != false ]; then
        record_failure "Expected self-lb option reject=false"
    fi
    if [ "$(ovn-nbctl get Load_Balancer "$load_balancer_uuid" selection_fields \
        | tr -d '[],\" ')" != ip_dst ]; then
        record_failure "Expected self-lb selection field ip_dst"
    fi
    if [ "$(ovn-nbctl --bare --columns=name find Logical_Switch \
        "load_balancer{>=}$load_balancer_uuid")" != self-moved ]; then
        record_failure "Expected self-lb only on self-moved"
    fi
    if [ "$(ovn-nbctl --bare --columns=name find Logical_Router \
        "load_balancer{>=}$load_balancer_uuid")" != self-r3 ]; then
        record_failure "Expected self-lb only on self-r3"
    fi
fi
if ovn-nbctl --bare --columns=_uuid find Load_Balancer \
    external_ids:ovn-tmt-tests-id=self-lb-delete | grep -q .; then
    record_failure "Expected deleted managed load balancer to be absent"
fi

check_static_route() {
    local id=$1
    local router=$2
    local prefix=$3
    local nexthop=$4
    local policy=$5
    local route_table=$6
    local output_port=$7
    local route_uuid

    route_uuid=$(ovn-nbctl --bare --columns=_uuid find \
        Logical_Router_Static_Route \
        external_ids:ovn-tmt-tests-id="$id" 2>/dev/null || true)
    if [ -z "$route_uuid" ]; then
        record_failure "Expected managed static route $id"
        return
    fi

    check_static_route_field "$id" parent "$router" \
        ovn-nbctl --bare --columns=name find Logical_Router \
        "static_routes{>=}$route_uuid"
    check_static_route_field "$id" ip_prefix "$prefix" \
        ovn-nbctl get Logical_Router_Static_Route "$route_uuid" ip_prefix
    check_static_route_field "$id" nexthop "$nexthop" \
        ovn-nbctl get Logical_Router_Static_Route "$route_uuid" nexthop
    check_static_route_field "$id" policy "$policy" \
        ovn-nbctl get Logical_Router_Static_Route "$route_uuid" policy
    check_static_route_field "$id" route_table "$route_table" \
        ovn-nbctl get Logical_Router_Static_Route "$route_uuid" route_table
    check_static_route_field "$id" output_port "$output_port" \
        ovn-nbctl get Logical_Router_Static_Route "$route_uuid" output_port
}

check_static_route_field() {
    local id=$1
    local field=$2
    local expected=$3
    local actual
    shift 3

    actual=$("$@" 2>/dev/null | tr -d '[]"' || true)
    if [ "$actual" != "$expected" ]; then
        record_failure "Expected static route $id $field=$expected, found $actual"
    fi
}

check_static_route self-route self-r3 2001:db8:ffff::/64 \
    2001:db8:2::1 dst-ip "" ""
check_static_route_id=$(ovn-nbctl --bare --columns=_uuid find \
    Logical_Router_Static_Route external_ids:ovn-tmt-tests-id=self-route)
if [ "$(</tmp/self-route-id)" != "$check_static_route_id" ] || \
    [ "$(</tmp/self-route-moved-id)" != "$check_static_route_id" ]; then
    record_failure "Expected static route identity to survive reconfiguration and reapply"
fi
if ovn-nbctl --bare --columns=_uuid find Logical_Router_Static_Route \
    external_ids:ovn-tmt-tests-id=self-route-delete | grep -q .; then
    record_failure "Expected deleted managed static route to be absent"
fi
if ! ovn-nbctl lr-route-list self-r3 | \
    grep -F -q '192.0.2.0/24'; then
    record_failure "Expected unmanaged static route to remain"
fi

assert_finish
