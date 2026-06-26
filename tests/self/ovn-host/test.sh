#!/bin/bash
set -e

echo "Checking ovn-controller process..."
pgrep -a ovn-controller

echo "Checking br-int bridge exists..."
ovs-vsctl list-br | grep br-int

echo "Checking OVS external-ids are configured..."
ovs-vsctl get open . external-ids:ovn-remote
ovs-vsctl get open . external-ids:ovn-encap-type
ovs-vsctl get open . external-ids:ovn-encap-ip
ovs-vsctl get open . external-ids:system-id

echo "Checking chassis is registered in SB database..."
ovn-sbctl show | grep Chassis

echo "All OVN host checks passed."
