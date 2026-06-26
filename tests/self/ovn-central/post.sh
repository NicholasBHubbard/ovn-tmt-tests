#!/bin/bash
set -e

echo "Checking ovsdb-server processes for NB and SB..."
pgrep -a ovsdb-server

echo "Checking ovn-northd process..."
pgrep -a ovn-northd

echo "Checking ovn-nbctl show..."
ovn-nbctl show

echo "Checking ovn-sbctl show..."
ovn-sbctl show

echo "Checking NB database listening on port 6641..."
ss -tlnp | grep 6641

echo "Checking SB database listening on port 6642..."
ss -tlnp | grep 6642

echo "All OVN central checks passed."
