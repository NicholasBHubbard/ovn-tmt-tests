#!/bin/bash
set -euo pipefail

source "$TMT_TREE/tests/lib/assert.sh"
source "$TMT_TREE/tests/lib/ovn.sh"
cd_repo_root

workdir=$(mktemp -d)
trap 'rm -rf "$workdir"' EXIT

echo "Checking ovsdb-server processes..."
assert_process_present ovsdb-server

echo "Checking ovn-northd process..."
assert_process_present ovn-northd

echo "Checking OVN databases..."
assert_ovn_nb_available
assert_ovn_sb_available

echo "Checking NB database listening on port 6641..."
assert_tcp_listening 6641

echo "Checking SB database listening on port 6642..."
assert_tcp_listening 6642

echo "Checking NB cluster status..."
if nb_status=$(ovn-appctl -t /var/run/ovn/ovnnb_db.ctl cluster/status OVN_Northbound 2>&1); then
    if echo "$nb_status" | grep -q "Role:"; then
        echo "$nb_status" | grep -E "^(Role|Status|Servers):"
    else
        record_failure "NB database is not in cluster mode"
    fi
else
    record_failure "NB cluster status check failed: $nb_status"
fi

echo "Checking SB cluster status..."
if sb_status=$(ovn-appctl -t /var/run/ovn/ovnsb_db.ctl cluster/status OVN_Southbound 2>&1); then
    if echo "$sb_status" | grep -q "Role:"; then
        echo "$sb_status" | grep -E "^(Role|Status|Servers):"
    else
        record_failure "SB database is not in cluster mode"
    fi
else
    record_failure "SB cluster status check failed: $sb_status"
fi

cat > "$workdir/inventory" <<'INVENTORY'
[leader]
leader-node ansible_connection=local

[follower]
follower-node ansible_connection=local
INVENTORY

if ! clustered_output=$(ansible-playbook -v -i "$workdir/inventory" \
    playbooks/ovn-clustered.yml --check --tags topology-resolution \
    -e ansible_become=false 2>&1); then
    record_failure "Cluster inventory-name fallback failed: $clustered_output"
elif ! grep -F -q '"ovn_cluster_members": ["leader-node", "follower-node"]' \
    <<< "$clustered_output"; then
    record_failure "Cluster topology did not fall back to inventory names"
fi

assert_finish
