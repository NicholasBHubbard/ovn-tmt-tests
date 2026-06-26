# Shared OVN/OVS assertions for repository self-tests.
if [ "${TEST_OVN_LIB_LOADED:-0}" = 1 ]; then
    return 0
fi
TEST_OVN_LIB_LOADED=1

source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/assert.sh"

assert_ovs_configured() {
    assert_command_present ovs-vsctl

    if command -v ovs-vsctl >/dev/null 2>&1 && ! ovs-vsctl show >/dev/null 2>&1; then
        record_failure "Expected OVS to be configured"
    fi
}

assert_ovs_unconfigured() {
    if command -v ovs-vsctl >/dev/null 2>&1 && ovs-vsctl show >/dev/null 2>&1; then
        record_failure "Precondition failed: OVS is already configured"
    fi
}

assert_ovs_bridge_present() {
    local bridge=$1

    assert_command_present ovs-vsctl

    if command -v ovs-vsctl >/dev/null 2>&1 && ! ovs-vsctl br-exists "$bridge" >/dev/null 2>&1; then
        record_failure "Expected OVS bridge to exist: $bridge"
    fi
}

assert_ovs_bridge_absent() {
    local bridge=$1

    if command -v ovs-vsctl >/dev/null 2>&1 && ovs-vsctl br-exists "$bridge" >/dev/null 2>&1; then
        record_failure "Precondition failed: OVS bridge already exists: $bridge"
    fi
}

assert_ovs_external_id_present() {
    local key=$1

    assert_command_present ovs-vsctl

    if command -v ovs-vsctl >/dev/null 2>&1 && ! ovs-vsctl get open . "external-ids:$key" >/dev/null 2>&1; then
        record_failure "Expected OVS external-ids:$key to be configured"
    fi
}

assert_ovs_external_id_absent() {
    local key=$1

    if command -v ovs-vsctl >/dev/null 2>&1 && ovs-vsctl get open . "external-ids:$key" >/dev/null 2>&1; then
        record_failure "Precondition failed: OVS external-ids:$key is already configured"
    fi
}

assert_ovn_nb_available() {
    assert_command_present ovn-nbctl

    if command -v ovn-nbctl >/dev/null 2>&1 && ! ovn-nbctl show >/dev/null 2>&1; then
        record_failure "Expected OVN northbound database to be accessible"
    fi
}

assert_ovn_nb_unavailable() {
    if command -v ovn-nbctl >/dev/null 2>&1 && ovn-nbctl show >/dev/null 2>&1; then
        record_failure "Precondition failed: OVN northbound database is already accessible"
    fi
}

assert_ovn_sb_available() {
    assert_command_present ovn-sbctl

    if command -v ovn-sbctl >/dev/null 2>&1 && ! ovn-sbctl show >/dev/null 2>&1; then
        record_failure "Expected OVN southbound database to be accessible"
    fi
}

assert_ovn_sb_unavailable() {
    if command -v ovn-sbctl >/dev/null 2>&1 && ovn-sbctl show >/dev/null 2>&1; then
        record_failure "Precondition failed: OVN southbound database is already accessible"
    fi
}

ovn_chassis_count() {
    ovn-sbctl show | grep -c "^Chassis" || true
}

assert_ovn_chassis_present() {
    local count

    assert_command_present ovn-sbctl

    if ! command -v ovn-sbctl >/dev/null 2>&1; then
        return
    fi

    count=$(ovn_chassis_count)
    echo "Found $count chassis registered"

    if [ "$count" -eq 0 ]; then
        record_failure "Expected at least one registered chassis"
        ovn-sbctl show || true
    fi
}

assert_ovn_chassis_count() {
    local expected=$1
    local count

    assert_command_present ovn-sbctl

    if ! command -v ovn-sbctl >/dev/null 2>&1; then
        return
    fi

    count=$(ovn_chassis_count)

    if [ "$count" -ne "$expected" ]; then
        record_failure "Expected $expected chassis, found $count"
        ovn-sbctl show || true
    else
        echo "Chassis count matches expected: $expected"
    fi
}
