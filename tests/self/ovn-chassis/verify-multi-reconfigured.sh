#!/bin/bash
set -euo pipefail

source "$TMT_TREE/tests/lib/assert.sh"

if podman container exists ovn-chassis-scale-a; then
    record_failure "Removed chassis container still exists: ovn-chassis-scale-a"
fi
if ovn-sbctl --bare --columns=name find chassis name=scale-a | grep -q .; then
    record_failure "Removed chassis remains registered: scale-a"
fi
if ! podman container exists ovn-chassis-scale-b; then
    record_failure "Expected retained chassis container: ovn-chassis-scale-b"
fi

mapping=$(podman exec ovn-chassis-scale-b ovs-vsctl get Open_vSwitch . \
    external_ids:ovn-bridge-mappings | tr -d '"')
if [ "$mapping" != provider:br-ex ]; then
    record_failure "Expected updated bridge mapping on scale-b"
fi

cms_options=$(podman exec ovn-chassis-scale-b ovs-vsctl get Open_vSwitch . \
    external_ids:ovn-cms-options | tr -d '"')
if [ "$cms_options" != enable-chassis-as-gw ]; then
    record_failure "Expected updated CMS options on scale-b"
fi

if ! podman exec ovn-chassis-scale-b ovs-vsctl br-exists br-ex; then
    record_failure "Expected updated bridge on scale-b: br-ex"
fi

if [ -f /tmp/ovn-chassis-scale-b-started ]; then
    started=$(podman inspect --format '{{.State.StartedAt}}' \
        ovn-chassis-scale-b)
    if [ "$started" != "$(cat /tmp/ovn-chassis-scale-b-started)" ]; then
        record_failure "Identical configuration restarted scale-b"
    fi
fi

assert_finish
