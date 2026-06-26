#!/bin/bash
set -e

echo "Checking openvswitch service..."
systemctl status openvswitch

echo "Checking ovs-vsctl..."
ovs-vsctl show

echo "Checking OVS binaries are in PATH..."
which ovs-vswitchd
which ovsdb-server

echo "All OVS checks passed."
