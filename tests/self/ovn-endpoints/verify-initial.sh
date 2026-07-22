#!/bin/bash
set -euo pipefail

endpoint_mtu() {
    ip -n "$1" -o link show dev "$1" | sed -n 's/.* mtu \([0-9]*\).*/\1/p'
}

ovn-nbctl --bare --columns=_uuid find Logical_Switch_Port name=self-port3 \
    > /tmp/self-port3-id
ovn-nbctl get Logical_Switch_Port self-port2 dynamic_addresses \
    | tr -d '"' | awk '{print $2}' > /tmp/self-port2-dynamic-address

test -s /tmp/self-port3-id
test -s /tmp/self-port2-dynamic-address
test "$(</sys/class/net/self-vm1-p/mtu)" = 1400
test "$(endpoint_mtu self-vm1)" = 1400
test "$(</sys/class/net/self-vm2-p/mtu)" = 1450
test "$(endpoint_mtu self-vm2)" = 1450
stat -Lc '%i' /var/run/netns/self-vm1 > /tmp/self-vm1-initial-ns-id
cat /sys/class/net/self-vm1-p/ifindex > /tmp/self-vm1-initial-ifindex
test -s /tmp/self-vm1-initial-ns-id
test -s /tmp/self-vm1-initial-ifindex
test "$(ovn-nbctl lsp-get-addresses self-port3 \
    | tr -d '\"')" = '02:00:00:00:03:01 dynamic'
test "$(ovn-nbctl get Logical_Switch_Port self-port1 \
    options:requested-chassis | tr -d '\"')" = default-0
test "$(ovn-nbctl get Logical_Switch_Port self-port1 \
    options:mcast_flood | tr -d '\"')" = false
test "$(ovn-nbctl get Logical_Switch_Port self-port3 dhcpv4_options \
    | tr -d '[]')" = "$(ovn-nbctl --bare --columns=_uuid find DHCP_Options \
    external_ids:ovn-tmt-tests-id=self-dhcp)"
test "$(ovn-nbctl get Logical_Switch_Port self-port3 dhcpv6_options \
    | tr -d '[]')" = "$(ovn-nbctl --bare --columns=_uuid find DHCP_Options \
    external_ids:ovn-tmt-tests-id=self-dhcp-v6)"
test "$(ip -n self-vm2 -4 -o address show dev self-vm2 scope global \
    | awk '{print $4}')" = "$(</tmp/self-port2-dynamic-address)/24"
ip -n self-vm2 -4 route show default \
    | grep -F -q 'default via 192.0.2.254 dev self-vm2'
test -s /run/ovn-tmt-tests/self-vm2-dhclient4.pid
test -s /run/ovn-tmt-tests/self-vm2-dhclient4.leases
cat /run/ovn-tmt-tests/self-vm2-dhclient4.pid > /tmp/self-vm2-dhclient4-pid
test "$(</tmp/self-vm2-initial-dhclient4-pid)" \
    != "$(</tmp/self-vm2-dhclient4-pid)"
if ps -p "$(</tmp/self-vm2-initial-dhclient4-pid)" -o args= 2>/dev/null \
    | grep -F -q dhclient; then
    exit 1
fi
kill -0 "$(</tmp/self-vm2-dhclient4-pid)"
ps -p "$(</tmp/self-vm2-dhclient4-pid)" -o args= \
    | grep -F -q -- '--timeout 10'
test -f /etc/netns/self-vm2/resolv.conf
grep -F -q 'nameserver 192.0.2.53' /etc/netns/self-vm2/resolv.conf
test "$(sha256sum /etc/resolv.conf | awk '{print $1}')" \
    = "$(</tmp/self-resolver-hash)"
