#!/bin/bash
set -e

echo "Checking OVN central services..."
pgrep -a ovsdb-server
pgrep -a ovn-northd

echo "Checking NB database is accessible..."
ovn-nbctl show

echo "Checking SB database is accessible..."
ovn-sbctl show

echo "Checking for registered chassis..."
CHASSIS_COUNT=$(ovn-sbctl show | grep -c "^Chassis" || true)
echo "Found $CHASSIS_COUNT chassis registered"

if [ "$CHASSIS_COUNT" -eq 0 ]; then
    echo "ERROR: No chassis registered"
    ovn-sbctl show
    exit 1
fi

if [ -n "$EXPECTED_CHASSIS" ]; then
    if [ "$CHASSIS_COUNT" -ne "$EXPECTED_CHASSIS" ]; then
        echo "ERROR: Expected $EXPECTED_CHASSIS chassis, found $CHASSIS_COUNT"
        ovn-sbctl show
        exit 1
    fi
    echo "Chassis count matches expected: $EXPECTED_CHASSIS"
fi

echo "Listing all registered chassis:"
ovn-sbctl show

echo "All multi-host topology checks passed."
