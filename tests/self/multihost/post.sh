#!/bin/bash
set -euo pipefail

source "$TMT_TREE/tests/lib/assert.sh"
source "$TMT_TREE/tests/lib/ovn.sh"
cd_repo_root

workdir=$(mktemp -d)
trap 'rm -rf "$workdir"' EXIT

echo "Checking OVN central services..."
assert_process_present ovsdb-server
assert_process_present ovn-northd

echo "Checking NB database is accessible..."
assert_ovn_nb_available

echo "Checking SB database is accessible..."
assert_ovn_sb_available

echo "Checking for registered chassis..."
assert_ovn_chassis_present

if [ -n "${EXPECTED_CHASSIS:-}" ]; then
    assert_ovn_chassis_count "$EXPECTED_CHASSIS"
fi

echo "Listing all registered chassis:"
ovn-sbctl show || true

cat > "$workdir/inventory" <<'INVENTORY'
[central]
central-node ansible_connection=local

[compute]
compute-node ansible_connection=local
INVENTORY

if ! multihost_output=$(ansible-playbook -v -i "$workdir/inventory" \
    playbooks/multihost.yml --check --tags topology-resolution \
    -e ansible_become=false 2>&1); then
    record_failure "Multihost inventory-name fallback failed: $multihost_output"
elif ! grep -F -q '"ovn_central_address": "central-node"' \
    <<< "$multihost_output"; then
    record_failure "Multihost topology did not fall back to the central inventory name"
fi

assert_finish
