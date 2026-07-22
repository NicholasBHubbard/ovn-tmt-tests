#!/bin/bash
set -euo pipefail

source "$TMT_TREE/tests/lib/assert.sh"

started=$(podman inspect --format '{{.State.StartedAt}}' ovn-chassis-scale-b)
if [ "$started" = "$(cat /tmp/ovn-chassis-scale-b-started)" ]; then
    record_failure "Updated chassis image did not recreate scale-b"
fi
if ! podman exec ovn-chassis-scale-b test -f /ovn-chassis-image-updated; then
    record_failure "Recreated scale-b did not use the updated image"
fi
if ! ovn-sbctl --bare --columns=name find chassis name=scale-b |
    grep -F -x -q scale-b; then
    record_failure "Recreated scale-b is not registered"
fi

assert_finish
