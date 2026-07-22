#!/bin/bash
set -euo pipefail

podman build \
    --tag localhost/ovn-chassis-selftest \
    --file "$TMT_TREE/tests/self/ovn-chassis/Containerfile" \
    "$TMT_TREE/tests/self/ovn-chassis"

podman network exists ovn-chassis-selftest ||
    podman network create --subnet 10.89.0.0/24 ovn-chassis-selftest
