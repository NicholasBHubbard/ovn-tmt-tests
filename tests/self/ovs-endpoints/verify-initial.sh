#!/bin/bash
set -euo pipefail

endpoint_mtu() {
    ip -n "$1" -o link show dev "$1" | sed -n 's/.* mtu \([0-9]*\).*/\1/p'
}

test "$(ovs-vsctl port-to-br self-direct-p)" = self-br-a
test "$(ovs-vsctl port-to-br self-peer-p)" = self-br-a
long_host_interface="ovse-$(printf %s self-long-endpoint-name | sha1sum | cut -c1-10)"
test "$(ovs-vsctl port-to-br "$long_host_interface")" = self-br-a
ip -n self-long-endpoint-name -o link show dev inside0 \
    | grep -F -q 'link/ether 02:00:00:00:20:07'
test "$(</sys/class/net/self-direct-p/mtu)" = 1400
test "$(endpoint_mtu self-direct)" = 1400
test "$(</sys/class/net/self-peer-p/mtu)" = 1450
test "$(endpoint_mtu self-peer)" = 1450
ip -n self-direct -o link show dev self-direct \
    | grep -F -q 'link/ether 02:00:00:00:20:01'
test "$(ip -n self-direct -o address show dev self-direct scope global \
    | awk '{print $4}' | sort)" = $'192.0.2.10/24\n2001:db8:1::10/64'
ip netns exec self-direct ping -c 1 -W 2 192.0.2.20
ip netns exec self-long-endpoint-name ping -c 1 -W 2 192.0.2.20
ip -n self-direct -4 route show default | grep -F -q \
    'default via 192.0.2.1 dev self-direct'
ip -n self-direct -4 route show table 100 198.51.100.0/24 | grep -F -q \
    '198.51.100.0/24 via 192.0.2.2 dev self-direct metric 10'
ip -n self-direct -6 route show table 200 default | grep -F -q \
    'default via 2001:db8:1::1 dev self-direct'

stat -Lc '%i' /var/run/netns/self-direct > /tmp/self-direct-initial-ns-id
cat /sys/class/net/self-direct-p/ifindex > /tmp/self-direct-initial-ifindex
test -s /tmp/self-direct-initial-ns-id
test -s /tmp/self-direct-initial-ifindex
