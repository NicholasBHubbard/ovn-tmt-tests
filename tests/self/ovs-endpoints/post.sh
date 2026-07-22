#!/bin/bash
set -euo pipefail

source "$TMT_TREE/tests/lib/assert.sh"

endpoint_mtu() {
    ip -n "$1" -o link show dev "$1" | sed -n 's/.* mtu \([0-9]*\).*/\1/p'
}

echo "Checking direct OVS endpoints..."
for endpoint in self-direct self-peer; do
    assert_command_runs "network namespace $endpoint" \
        ip netns exec "$endpoint" true
    assert_command_runs "host interface ${endpoint}-p" \
        ip link show "${endpoint}-p"
    if [ "$(ovs-vsctl port-to-br "${endpoint}-p" 2>/dev/null)" != self-br-b ]; then
        record_failure "Expected ${endpoint}-p on self-br-b"
    fi
done

long_host_interface="ovse-$(printf %s self-long-endpoint-name | sha1sum | cut -c1-10)"
if [ "$(ovs-vsctl port-to-br "$long_host_interface" 2>/dev/null)" != self-br-b ]; then
    record_failure "Expected long-name endpoint on self-br-b"
fi
if ! ip -n self-long-endpoint-name -o link show dev endpoint0 \
    | grep -F -q 'link/ether 02:00:00:00:20:17'; then
    record_failure "Expected reconfigured long-name endpoint interface"
fi
ip netns exec self-long-endpoint-name ping -c 1 -W 2 203.0.113.20 || \
    record_failure "Expected long-name endpoint connectivity across self-br-b"

if [ "$(</sys/class/net/self-direct-p/mtu)" != 1500 ] || \
    [ "$(endpoint_mtu self-direct)" != 1500 ]; then
    record_failure "Expected self-direct MTU to return to the default 1500"
fi
if [ "$(</sys/class/net/self-peer-p/mtu)" != 1300 ] || \
    [ "$(endpoint_mtu self-peer)" != 1300 ]; then
    record_failure "Expected self-peer MTU override 1300"
fi
if ! ip -n self-direct -o link show dev self-direct \
    | grep -F -q 'link/ether 02:00:00:00:20:11'; then
    record_failure "Expected updated self-direct MAC address"
fi
if [ "$(ip -n self-direct -o address show dev self-direct scope global \
    | awk '{print $4}')" != 203.0.113.10/24 ]; then
    record_failure "Expected replaced self-direct addresses"
fi
ip netns exec self-direct ping -c 1 -W 2 203.0.113.20 || \
    record_failure "Expected connectivity across self-br-b"
ip -n self-direct -4 route show default \
    | grep -F -q 'default via 203.0.113.1 dev self-direct' || \
    record_failure "Expected replaced self-direct default route"
ip -n self-direct -4 route show table 101 198.51.100.0/24 \
    | grep -F -q '198.51.100.0/24 via 203.0.113.2 dev self-direct metric 20' || \
    record_failure "Expected replaced self-direct policy route"
if ip -n self-direct -4 route show table 100 2>/dev/null | grep -q .; then
    record_failure "Expected stale self-direct IPv4 routes to be removed"
fi
if ip -n self-direct -6 route show table 200 2>/dev/null | grep -q .; then
    record_failure "Expected stale self-direct IPv6 routes to be removed"
fi

ns_id=$(stat -Lc '%i' /var/run/netns/self-direct)
if [ "$ns_id" != "$(</tmp/self-direct-initial-ns-id)" ] || \
    [ "$ns_id" != "$(</tmp/self-direct-ns-id)" ]; then
    record_failure "Expected bridge move and reapply to preserve the namespace"
fi
ifindex=$(</sys/class/net/self-direct-p/ifindex)
if [ "$ifindex" != "$(</tmp/self-direct-initial-ifindex)" ] || \
    [ "$ifindex" != "$(</tmp/self-direct-ifindex)" ]; then
    record_failure "Expected bridge move and reapply to preserve the veth"
fi

for endpoint in self-delete self-away self-stale; do
    if ip netns list | grep -q "^${endpoint}\\b"; then
        record_failure "Expected endpoint namespace to be absent: $endpoint"
    fi
    if ip link show "${endpoint}-p" >/dev/null 2>&1; then
        record_failure "Expected endpoint veth to be absent: ${endpoint}-p"
    fi
    if ovs-vsctl port-to-br "${endpoint}-p" >/dev/null 2>&1; then
        record_failure "Expected OVS port to be absent: ${endpoint}-p"
    fi
done

if [ "$(ovs-vsctl port-to-br self-keep-p 2>/dev/null)" != self-br-a ] || \
    [ "$(endpoint_mtu self-keep)" != 1450 ]; then
    record_failure "Expected unlisted self-keep endpoint to remain unchanged"
fi

assert_finish
