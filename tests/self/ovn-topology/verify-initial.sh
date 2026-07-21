#!/bin/bash
set -euo pipefail

ovn-nbctl --bare --columns=_uuid find Logical_Router_Port name=self-rp \
    > /tmp/self-rp-id
ovn-nbctl --bare --columns=_uuid find Logical_Switch name=self-moved \
    > /tmp/self-moved-id
ovn-nbctl --bare --columns=_uuid find Logical_Switch_Port name=self-rp-sw \
    > /tmp/self-rp-sw-id
ovn-nbctl --bare --columns=_uuid find Logical_Router_Port name=self-rp-delete \
    > /tmp/self-rp-delete-id
ovn-nbctl --bare --columns=_uuid find Logical_Switch_Port name=self-rp-delete-sw \
    > /tmp/self-rp-delete-sw-id
ovn-nbctl --bare --columns=_uuid find Logical_Switch_Port name=self-localnet \
    > /tmp/self-localnet-id
ovn-nbctl --bare --columns=_uuid find Logical_Switch_Port name=self-localnet-delete \
    > /tmp/self-localnet-delete-id
ovn-nbctl --bare --columns=_uuid find Gateway_Chassis name=self-gateway \
    > /tmp/self-gateway-id
ovn-nbctl --bare --columns=_uuid find Gateway_Chassis name=self-gateway-secondary \
    > /tmp/self-gateway-secondary-id
ovn-nbctl --bare --columns=_uuid find Gateway_Chassis name=self-gateway-delete \
    > /tmp/self-gateway-delete-id
ovn-nbctl --bare --columns=_uuid find DHCP_Options \
    external_ids:ovn-tmt-tests-id=self-dhcp > /tmp/self-dhcp-id
ovn-nbctl --bare --columns=_uuid find DHCP_Options \
    external_ids:ovn-tmt-tests-id=self-dhcp-v6 > /tmp/self-dhcp-v6-id
ovn-nbctl --bare --columns=_uuid find DHCP_Options \
    external_ids:ovn-tmt-tests-id=self-dhcp-delete > /tmp/self-dhcp-delete-id
ovn-nbctl --bare --columns=_uuid find NAT \
    external_ids:ovn-tmt-tests-id=self-nat > /tmp/self-nat-id
ovn-nbctl --bare --columns=_uuid find NAT \
    external_ids:ovn-tmt-tests-id=self-nat-snat > /tmp/self-nat-snat-id
ovn-nbctl --bare --columns=_uuid find NAT \
    external_ids:ovn-tmt-tests-id=self-nat-delete > /tmp/self-nat-delete-id
ovn-nbctl --bare --columns=_uuid find Logical_Router_Static_Route \
    external_ids:ovn-tmt-tests-id=self-route > /tmp/self-route-id
ovn-nbctl --bare --columns=_uuid find Logical_Router_Static_Route \
    external_ids:ovn-tmt-tests-id=self-route-delete > /tmp/self-route-delete-id

for path in \
    /tmp/self-rp-id \
    /tmp/self-moved-id \
    /tmp/self-rp-sw-id \
    /tmp/self-rp-delete-id \
    /tmp/self-rp-delete-sw-id \
    /tmp/self-localnet-id \
    /tmp/self-localnet-delete-id \
    /tmp/self-gateway-id \
    /tmp/self-gateway-secondary-id \
    /tmp/self-gateway-delete-id \
    /tmp/self-dhcp-id \
    /tmp/self-dhcp-v6-id \
    /tmp/self-dhcp-delete-id \
    /tmp/self-nat-id \
    /tmp/self-nat-snat-id \
    /tmp/self-nat-delete-id \
    /tmp/self-route-id \
    /tmp/self-route-delete-id; do
    test -s "$path"
done

test "$(ovn-nbctl get Logical_Switch self-moved other_config:subnet \
    | tr -d '\"')" = 203.0.113.0/24
test "$(ovn-nbctl get Logical_Switch self-moved other_config:exclude_ips \
    | tr -d '\"')" = 203.0.113.1..203.0.113.2
test "$(ovn-nbctl get Logical_Switch self-moved other_config:mcast_snoop \
    | tr -d '\"')" = true

test "$(ovn-nbctl get Logical_Router_Static_Route \
    "$(</tmp/self-route-id)" ip_prefix | tr -d '\"')" = 198.51.100.0/24
test "$(ovn-nbctl get Logical_Router_Static_Route \
    "$(</tmp/self-route-id)" nexthop | tr -d '\"')" = 192.0.2.1
test "$(ovn-nbctl get Logical_Router_Static_Route \
    "$(</tmp/self-route-id)" policy | tr -d '[]\"')" = src-ip
test "$(ovn-nbctl get Logical_Router_Static_Route \
    "$(</tmp/self-route-id)" route_table | tr -d '\"')" = blue
test "$(ovn-nbctl get Logical_Router_Static_Route \
    "$(</tmp/self-route-id)" output_port | tr -d '[]\"')" = self-rp
test "$(ovn-nbctl get Logical_Router_Static_Route \
    "$(</tmp/self-route-delete-id)" policy | tr -d '[]\"')" = dst-ip
test -z "$(ovn-nbctl get Logical_Router_Static_Route \
    "$(</tmp/self-route-delete-id)" route_table | tr -d '[]\"')"
test -z "$(ovn-nbctl get Logical_Router_Static_Route \
    "$(</tmp/self-route-delete-id)" output_port | tr -d '[]\"')"
test "$(ovn-nbctl --bare --columns=name find Logical_Router \
    "ports{>=}$(</tmp/self-rp-id)")" = self-r1
test "$(ovn-nbctl --bare --columns=name find Logical_Switch \
    "ports{>=}$(</tmp/self-rp-sw-id)")" = self-sw

test "$(ovn-nbctl --bare --columns=name find Logical_Switch \
    "ports{>=}$(</tmp/self-localnet-id)")" = self-sw
test "$(ovn-nbctl get Logical_Switch_Port self-localnet type \
    | tr -d '\"')" = localnet
test "$(ovn-nbctl get Logical_Switch_Port self-localnet options:network_name \
    | tr -d '\"')" = self-provider
test "$(ovn-nbctl lsp-get-addresses self-localnet | tr -d '\"')" = unknown
test "$(ovn-nbctl lsp-get-tag self-localnet)" = 100

test "$(ovn-nbctl --bare --columns=name find Logical_Router_Port \
    "gateway_chassis{>=}$(</tmp/self-gateway-id)")" = self-rp-gateway
test "$(ovn-nbctl get Gateway_Chassis "$(</tmp/self-gateway-id)" chassis_name \
    | tr -d '\"')" = self-gateway-1
test "$(ovn-nbctl get Gateway_Chassis "$(</tmp/self-gateway-id)" priority)" = 20
test "$(ovn-nbctl get Gateway_Chassis \
    "$(</tmp/self-gateway-secondary-id)" priority)" = 0

test "$(ovn-nbctl get DHCP_Options "$(</tmp/self-dhcp-id)" cidr \
    | tr -d '\"')" = 192.0.2.0/24
test "$(ovn-nbctl get DHCP_Options "$(</tmp/self-dhcp-id)" options:lease_time \
    | tr -d '\"')" = 3600
test "$(ovn-nbctl get DHCP_Options "$(</tmp/self-dhcp-id)" \
    options:ip_forward_enable | tr -d '\"')" = 0
test "$(ovn-nbctl get DHCP_Options "$(</tmp/self-dhcp-v6-id)" cidr \
    | tr -d '\"')" = 2001:db8:1::/64
test "$(ovn-nbctl get DHCP_Options "$(</tmp/self-dhcp-v6-id)" \
    options:dns_server | tr -d '\"')" = 2001:db8::53

test "$(ovn-nbctl get NAT "$(</tmp/self-nat-id)" type \
    | tr -d '\"')" = dnat_and_snat
test "$(ovn-nbctl get NAT "$(</tmp/self-nat-id)" external_ip \
    | tr -d '\"')" = 198.51.100.10
test "$(ovn-nbctl get NAT "$(</tmp/self-nat-id)" logical_ip \
    | tr -d '\"')" = 192.0.2.1
test "$(ovn-nbctl get NAT "$(</tmp/self-nat-id)" logical_port \
    | tr -d '[]\"')" = self-port1
test "$(ovn-nbctl get NAT "$(</tmp/self-nat-id)" external_mac \
    | tr -d '[]\"')" = 02:00:00:00:01:01
test "$(ovn-nbctl get NAT "$(</tmp/self-nat-id)" external_port_range \
    | tr -d '\"')" = 10000-20000
test "$(ovn-nbctl get NAT "$(</tmp/self-nat-id)" gateway_port \
    | tr -d '[]')" = "$(</tmp/self-rp-id)"
test "$(ovn-nbctl get NAT "$(</tmp/self-nat-id)" match \
    | tr -d '\"')" = 'ip4.src == 192.0.2.0/24'
test "$(ovn-nbctl get NAT "$(</tmp/self-nat-id)" priority)" = 100
test "$(ovn-nbctl get NAT "$(</tmp/self-nat-id)" options:stateless \
    | tr -d '\"')" = true
test "$(ovn-nbctl get NAT "$(</tmp/self-nat-id)" options:add_route \
    | tr -d '\"')" = true
test "$(ovn-nbctl get NAT "$(</tmp/self-nat-snat-id)" type \
    | tr -d '\"')" = snat
test "$(ovn-nbctl get NAT "$(</tmp/self-nat-snat-id)" external_ip \
    | tr -d '\"')" = 198.51.100.20
test "$(ovn-nbctl get NAT "$(</tmp/self-nat-snat-id)" logical_ip \
    | tr -d '\"')" = 192.0.2.0/24
test "$(ovn-nbctl get NAT "$(</tmp/self-nat-snat-id)" priority)" = 0
test "$(ovn-nbctl --bare --columns=name find Logical_Router \
    "static_routes{>=}$(</tmp/self-route-id)")" = self-r1
test "$(ovn-nbctl --bare --columns=name find Logical_Router \
    "nat{>=}$(</tmp/self-nat-id)")" = self-r1
