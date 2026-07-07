#!/bin/bash
set -euo pipefail

source "$TMT_TREE/tests/lib/assert.sh"
source "$TMT_TREE/tests/lib/ovn.sh"

echo "Checking ovsdb-server processes for NB and SB..."
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

echo "Checking NB connection uses SSL..."
nb_conn=$(ovn-nbctl get-connection)
if [[ "$nb_conn" != *"pssl:"* ]]; then
    record_failure "Expected NB connection to use pssl, got: $nb_conn"
fi

echo "Checking SB connection uses SSL..."
sb_conn=$(ovn-sbctl get-connection)
if [[ "$sb_conn" != *"pssl:"* ]]; then
    record_failure "Expected SB connection to use pssl, got: $sb_conn"
fi

assert_finish
