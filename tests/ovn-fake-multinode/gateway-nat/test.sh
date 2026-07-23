#!/bin/bash
set -euo pipefail

# tmt creates this file at runtime.
# shellcheck disable=SC1090
source "$TMT_TOPOLOGY_BASH"

case "${TMT_GUEST[name]}" in
    compute-1)
        namespace=nat-internal
        destination=192.0.2.50
        description="SNAT connectivity to the external endpoint"
        ;;
    gateway-1)
        namespace=nat-external
        destination=192.0.2.100
        description="DNAT connectivity to the internal endpoint"
        if ip -n "$namespace" route show default | grep -q .; then
            echo "External endpoint must not have a route to the private network" >&2
            exit 1
        fi
        ;;
    *)
        echo "Unexpected test guest: ${TMT_GUEST[name]}" >&2
        exit 1
        ;;
esac

ip netns list | grep -q "^${namespace}\b"

for _ in {1..30}; do
    if ip netns exec "$namespace" ping -c 1 -W 1 "$destination"; then
        exit 0
    fi
    sleep 1
done

echo "No $description from $namespace to $destination" >&2
exit 1
