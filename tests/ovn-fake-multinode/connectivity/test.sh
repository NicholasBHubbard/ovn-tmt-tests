#!/bin/bash
set -euo pipefail

source "$TMT_TREE/tests/lib/multihost.sh"
multihost_run_playbook "$PWD/setup.yml"

multihost_exec compute-1 ip netns exec sw0p1 true
multihost_exec compute-2 ip netns exec sw0p2 true
multihost_exec compute-2 ip netns exec sw1p1 true

multihost_wait_for_ping compute-1 sw0p1 10.0.0.4

ovn-nbctl pg-add pg0 sw0-port1 sw0-port2
ovn-nbctl acl-add pg0 to-lport 1001 \
    'outport == @pg0 && ip4' drop
ovn-nbctl --wait=sb sync
multihost_expect_no_ping compute-1 sw0p1 10.0.0.4

ovn-nbctl acl-add pg0 to-lport 1002 \
    'outport == @pg0 && ip4 && icmp' allow-related
ovn-nbctl --wait=sb sync
multihost_wait_for_ping compute-1 sw0p1 10.0.0.4

multihost_wait_for_ping compute-1 sw0p1 20.0.0.3

ovn-nbctl lsp-set-addresses sw1-port1 unknown
ovn-nbctl --wait=hv sync
multihost_wait_for_ping compute-1 sw0p1 20.0.0.3
