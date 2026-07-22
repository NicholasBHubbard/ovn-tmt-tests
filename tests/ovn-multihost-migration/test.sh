#!/bin/bash
set -euo pipefail

source "$TMT_TREE/tests/lib/multihost.sh"

set_requested_chassis() {
    ovn-nbctl --wait=hv set Logical_Switch_Port mig-port \
        "options:requested-chassis=$1"
}

restore_migration_source() {
    multihost_exec compute-1 ovs-vsctl set Interface mig-src-p \
        external_ids:iface-id=mig-port >/dev/null 2>&1 || true
    set_requested_chassis compute-1 >/dev/null 2>&1 || true
}
trap restore_migration_source EXIT

set_requested_chassis compute-1
multihost_wait_for_ping compute-1 mig-src 10.30.0.2
multihost_expect_no_ping compute-3 mig-dst 10.30.0.2

set_requested_chassis compute-1,compute-3
multihost_wait_for_ping compute-1 mig-src 10.30.0.2
multihost_wait_for_ping compute-3 mig-dst 10.30.0.2

set_requested_chassis compute-3
multihost_expect_no_ping compute-1 mig-src 10.30.0.2
multihost_wait_for_ping compute-3 mig-dst 10.30.0.2

multihost_exec compute-1 ovs-vsctl remove Interface mig-src-p external_ids iface-id
multihost_exec compute-1 ovn-appctl -t ovn-controller recompute
ovn-nbctl --wait=sb sync
multihost_wait_for_ping compute-3 mig-dst 10.30.0.2
