#!/bin/bash
set -euo pipefail

source "$TMT_TREE/tests/lib/assert.sh"
source "$TMT_TREE/tests/lib/multihost.sh"
source "$TMT_TREE/tests/lib/ovn.sh"
cd_repo_root

inventory=$(mktemp)
trap 'rm -f "$inventory"' EXIT

echo "Checking test-scoped Ansible setup..."
multihost_run_playbook "$TMT_TREE/tests/self/multihost/test-setup.yml"
if ! grep -Fq 'TASK [Confirm test-scoped setup reaches each guest]' \
    "$TMT_TEST_DATA/setup.log"; then
    record_failure "Test-scoped setup log did not contain the Ansible task output"
fi
for guest in $TMT_GUEST_NAMES; do
    guest_log="$TMT_TEST_DATA/setup-$guest.log"
    if ! grep -Fq 'TASK [Confirm test-scoped setup reaches each guest]' \
        "$guest_log"; then
        record_failure "Test-scoped setup did not retain the $guest Ansible log"
    fi
    recap_hosts=$(awk '$2 == ":" && $3 ~ /^ok=/ { print $1 }' "$guest_log")
    if [ "$recap_hosts" != "$guest" ]; then
        record_failure "$guest setup log contains other guests: $recap_hosts"
    fi
done

echo "Checking top-down debug arguments..."
debug_args=$(mktemp)
debug_log=$(mktemp)
if ! (
    ansible-playbook() {
        printf '%s\n' "$*" > "$debug_args"
    }
    MULTIHOST_SETUP_LOG=$debug_log OTT_TEST_DEBUG=true multihost_run_playbook \
        "$TMT_TREE/tests/self/multihost/test-setup.yml"
); then
    record_failure "Debug playbook invocation failed"
elif ! grep -Eq '(^| )-vvv( |$)' "$debug_args"; then
    record_failure "OTT_TEST_DEBUG=true did not enable Ansible -vvv output"
fi
rm -f "$debug_args" "$debug_log" "${debug_log%.log}"-*.log

echo "Checking test-scoped setup failure propagation..."
failure_log=$(mktemp)
if (
    ansible-playbook() {
        return 42
    }
    MULTIHOST_SETUP_LOG=$failure_log multihost_run_playbook \
        "$TMT_TREE/tests/self/multihost/test-setup.yml"
); then
    record_failure "Test-scoped setup ignored an Ansible failure"
elif [ "$?" -ne 42 ]; then
    record_failure "Test-scoped setup did not preserve the Ansible failure status"
fi
rm -f "$failure_log" "${failure_log%.log}"-*.log

echo "Checking top-down shell tracing..."
if ! trace_output=$(OTT_TEST_DEBUG=true bash -c \
    'source "$TMT_TREE/tests/lib/multihost.sh"; echo trace-marker' 2>&1); then
    record_failure "Debug shell tracing failed"
elif ! grep -Eq '^\+ .*echo trace-marker$' <<< "$trace_output"; then
    record_failure "OTT_TEST_DEBUG=true did not enable shell tracing"
fi

echo "Checking OVN central services..."
assert_process_present ovsdb-server
assert_process_present ovn-northd

echo "Checking NB database is accessible..."
assert_ovn_nb_available

echo "Checking SB database is accessible..."
assert_ovn_sb_available

echo "Checking for registered chassis..."
assert_ovn_chassis_present

if [ "${OTT_SSL_ENABLED:-false}" = true ]; then
    echo "Checking end-to-end OVN TLS..."
    central_address=$(multihost_guest_hostname central)
    if [[ $(ovn-nbctl get-connection) != *pssl:* ]]; then
        record_failure "OVN NB database is not listening with TLS"
    fi
    if [[ $(ovn-sbctl get-connection) != *pssl:* ]]; then
        record_failure "OVN SB database is not listening with TLS"
    fi
    for guest in ${TMT_ROLES[compute]}; do
        ovn_remote=$(multihost_exec "$guest" ovs-vsctl get Open_vSwitch . \
            external_ids:ovn-remote | tr -d '"')
        if [[ "$ovn_remote" != ssl:* ]]; then
            record_failure "$guest OVN remote is not using TLS: $ovn_remote"
        fi
        if ! multihost_exec "$guest" test -s \
            /run/ovn-test-pki/certificate.pem; then
            record_failure "$guest is missing its managed OVN certificate"
        fi
    done
    if ! multihost_exec compute-1 ovn-nbctl \
        --db="ssl:$central_address:6641" \
        --private-key=/run/ovn-test-pki/private-key.pem \
        --certificate=/run/ovn-test-pki/certificate.pem \
        --ca-cert=/run/ovn-test-pki/ca-cert.pem show; then
        record_failure "Remote OVN NB TLS connection failed"
    fi
    if ! multihost_exec compute-1 ovn-sbctl \
        --db="ssl:$central_address:6642" \
        --private-key=/run/ovn-test-pki/private-key.pem \
        --certificate=/run/ovn-test-pki/certificate.pem \
        --ca-cert=/run/ovn-test-pki/ca-cert.pem show; then
        record_failure "Remote OVN SB TLS connection failed"
    fi
    if ! multihost_wait_for_ping compute-1 self-tls-a 192.0.2.22; then
        record_failure "OVN packet traffic failed while controllers used TLS"
    fi

    echo "Checking TLS to TCP reconfiguration..."
    multihost_run_playbook "$TMT_TREE/playbooks/multihost.yml" \
        -e ovn_multihost_ssl_enabled=false
    multihost_run_playbook "$TMT_TREE/playbooks/ovn-test-pki-install.yml" \
        -e ovn_test_pki_enabled=false
    if [[ $(ovn-nbctl get-connection) != *ptcp:* ]]; then
        record_failure "OVN NB database did not return to TCP"
    fi
    if [[ $(ovn-sbctl get-connection) != *ptcp:* ]]; then
        record_failure "OVN SB database did not return to TCP"
    fi
    if [ -n "$(ovn-nbctl get-ssl)" ]; then
        record_failure "OVN NB database retained stale SSL configuration"
    fi
    if [ -n "$(ovn-sbctl get-ssl)" ]; then
        record_failure "OVN SB database retained stale SSL configuration"
    fi
    for guest in ${TMT_ROLES[compute]}; do
        ovn_remote=$(multihost_exec "$guest" ovs-vsctl get Open_vSwitch . \
            external_ids:ovn-remote | tr -d '"')
        if [[ "$ovn_remote" != tcp:* ]]; then
            record_failure "$guest OVN remote did not return to TCP: $ovn_remote"
        fi
    done
    for guest in $TMT_GUEST_NAMES; do
        if [ -n "$(multihost_exec "$guest" ovs-vsctl get-ssl)" ]; then
            record_failure "$guest retained stale OVS SSL configuration"
        fi
        if multihost_exec "$guest" test -e \
            /run/ovn-test-pki; then
            record_failure "$guest retained managed OVN certificates"
        fi
    done
    if ! multihost_wait_for_ping compute-1 self-tls-a 192.0.2.22; then
        record_failure "OVN packet traffic failed after returning to TCP"
    fi
fi

echo "Checking cross-guest command execution..."
if [ -n "${OTT_MULTIHOST_TEST_GUEST:-}" ]; then
    remote_name=$(multihost_exec "$OTT_MULTIHOST_TEST_GUEST" hostname)
    if [ -z "$remote_name" ]; then
        record_failure "Cross-guest command returned an empty hostname"
    fi

    if multihost_exec "$OTT_MULTIHOST_TEST_GUEST" false; then
        record_failure "Cross-guest command did not preserve a failure exit status"
    fi
fi

echo "Checking cross-guest connectivity assertions..."
if ! (
    multihost_exec() { return 0; }
    multihost_wait_for_ping compute-1 endpoint 192.0.2.1 1 &&
        ! multihost_expect_no_ping compute-1 endpoint 192.0.2.1
); then
    record_failure "Connectivity helpers rejected mocked connectivity"
fi

if ! (
    multihost_exec() { return 1; }
    ! multihost_wait_for_ping compute-1 endpoint 192.0.2.1 1 &&
        multihost_expect_no_ping compute-1 endpoint 192.0.2.1
); then
    record_failure "Connectivity helpers accepted mocked failure"
fi

if [ -n "${OTT_EXPECTED_CHASSIS:-}" ]; then
    assert_ovn_chassis_count "$OTT_EXPECTED_CHASSIS"
fi

if [ "${OTT_EXPECTED_CHASSIS:-}" = 2 ]; then
    echo "Checking provider mesh connectivity..."
    if ! multihost_wait_for_ping compute-1 self-provider-1 192.0.2.2; then
        record_failure "Provider mesh did not carry endpoint traffic"
    fi
    if ! multihost_wait_for_ping central self-provider-0 192.0.2.2; then
        record_failure "Provider hub did not carry spoke-to-spoke traffic"
    fi

    for guest_and_count in central:1 compute-1:2 compute-2:1; do
        guest=${guest_and_count%:*}
        expected=${guest_and_count#*:}
        actual=$(multihost_exec "$guest" ovs-vsctl --bare --columns=name \
            find Interface external_ids:ovn-tmt-tests-mesh=self-provider \
            | sed '/^$/d' | wc -l)
        if [ "$actual" != "$expected" ]; then
            record_failure \
                "Expected $expected provider tunnel(s) on $guest, found $actual"
        fi
    done
fi

echo "Listing all registered chassis:"
ovn-sbctl show || true

printf '%s\n' '[central]' 'central-node ansible_connection=local' '' \
    '[compute]' 'compute-node ansible_connection=local' > "$inventory"

if ! multihost_output=$(ansible-playbook -v -i "$inventory" \
    playbooks/multihost.yml --check --tags topology-resolution \
    -e ansible_become=false 2>&1); then
    record_failure "Multihost inventory-name fallback failed: $multihost_output"
elif ! grep -F -q '"ovn_central_address": "central-node"' \
    <<< "$multihost_output"; then
    record_failure "Multihost topology did not fall back to the central inventory name"
fi

assert_finish
