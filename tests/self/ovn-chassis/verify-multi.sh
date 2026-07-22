#!/bin/bash
set -euo pipefail

source "$TMT_TREE/tests/lib/assert.sh"

for chassis in scale-a scale-b; do
    container="ovn-chassis-$chassis"
    if ! podman container exists "$container"; then
        record_failure "Expected chassis container: $container"
    fi
    if ! ovn-sbctl --bare --columns=name find chassis name="$chassis" |
        grep -F -x -q "$chassis"; then
        record_failure "Expected registered chassis: $chassis"
    fi
done

ovn-nbctl --if-exists ls-del scale-test
ovn-nbctl ls-add scale-test \
    -- lsp-add scale-test scale-a-port \
    -- lsp-set-addresses scale-a-port '02:00:00:00:00:0a 192.0.2.10' \
    -- lsp-add scale-test scale-b-port \
    -- lsp-set-addresses scale-b-port '02:00:00:00:00:0b 192.0.2.11'

for chassis in scale-a scale-b; do
    container="ovn-chassis-$chassis"
    suffix=${chassis#scale-}
    if [ "$suffix" = a ]; then
        mac=02:00:00:00:00:0a
        address=192.0.2.10/24
    else
        mac=02:00:00:00:00:0b
        address=192.0.2.11/24
    fi
    podman exec "$container" ovs-vsctl --may-exist add-port br-int endpoint0 \
        -- set Interface endpoint0 type=internal \
        external_ids:iface-id="$chassis-port"
    podman exec "$container" ip link set endpoint0 address "$mac"
    podman exec "$container" ip address replace "$address" dev endpoint0
    podman exec "$container" ip link set endpoint0 up
done

for _ in {1..30}; do
    if podman exec ovn-chassis-scale-a ping -c 1 -W 1 192.0.2.11; then
        assert_finish
    fi
    sleep 1
done

record_failure "Synthetic chassis could not exchange packets"
assert_finish
