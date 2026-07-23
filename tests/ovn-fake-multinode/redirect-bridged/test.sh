#!/bin/bash
set -euo pipefail

source "$TMT_TREE/tests/lib/multihost.sh"
multihost_run_playbook "$PWD/setup.yml"

redirect_type=$(ovn-nbctl --bare get Logical_Router_Port rr-public options:redirect-type)
if [ "$redirect_type" != bridged ]; then
    echo "rr-public does not use redirect-type=bridged" >&2
    exit 1
fi

gateway_chassis=$(ovn-sbctl --bare --columns=_uuid find Chassis name=gateway-1)
redirect_chassis=$(ovn-sbctl --bare --columns=chassis \
    find Port_Binding logical_port=cr-rr-public)
if [[ "$redirect_chassis" != *"$gateway_chassis"* ]]; then
    echo "rr-public redirect port is not resident on gateway-1" >&2
    exit 1
fi

multihost_wait_for_ping compute-1 rr-vm1 20.10.0.2
