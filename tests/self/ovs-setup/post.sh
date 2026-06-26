#!/bin/bash
set -e

echo "Checking ovs-vsctl..."
ovs-vsctl show

echo "Checking OVS binaries are in PATH..."
command -v ovs-vswitchd
command -v ovsdb-server

if command -v pgrep >/dev/null 2>&1; then
    echo "Checking OVS processes..."
    pgrep -a ovsdb-server
fi

echo "All OVS checks passed."
