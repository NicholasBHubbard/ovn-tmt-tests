#!/bin/bash
set -euo pipefail

source "$(dirname "$0")/../../lib/assert.sh"
source "$(dirname "$0")/../../lib/ovn.sh"

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

assert_finish
