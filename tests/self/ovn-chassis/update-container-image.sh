#!/bin/bash
set -euo pipefail

podman run --name ovn-chassis-image-update \
    localhost/ovn-chassis-selftest \
    touch /ovn-chassis-image-updated
podman commit --change 'CMD ["sleep", "infinity"]' \
    ovn-chassis-image-update localhost/ovn-chassis-selftest
podman rm ovn-chassis-image-update
