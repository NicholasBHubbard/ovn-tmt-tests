#!/bin/bash
set -euo pipefail

# tmt creates this file at runtime.
# shellcheck disable=SC1090
source "$TMT_TOPOLOGY_BASH"

case "${TMT_GUEST[name]}" in
    compute-1)
        namespace=tmt-vm1
        peer=10.0.0.2
        ;;
    compute-2)
        namespace=tmt-vm2
        peer=10.0.0.1
        ;;
    *)
        echo "Unexpected test guest: ${TMT_GUEST[name]}" >&2
        exit 1
        ;;
esac

ip netns list | grep -q "^${namespace}\b"

for _ in {1..30}; do
    if ip netns exec "$namespace" ping -c 1 -W 1 "$peer"; then
        exit 0
    fi
    sleep 1
done

echo "No connectivity from $namespace to $peer" >&2
exit 1
