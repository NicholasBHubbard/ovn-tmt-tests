#!/bin/bash
set -euo pipefail

source "$TMT_TREE/tests/lib/multihost.sh"

restore_provider_localnet() {
    ovn-nbctl --may-exist lsp-add npl-public npl-localnet \
        -- lsp-set-type npl-localnet localnet \
        -- lsp-set-addresses npl-localnet unknown \
        -- lsp-set-options npl-localnet network_name=public \
        >/dev/null 2>&1 || true
}
trap restore_provider_localnet EXIT

run_traffic() {
    multihost_wait_for_ping compute-1 npl-private-a1 172.30.0.100
    multihost_wait_for_ping compute-1 npl-private-a1 172.30.0.110
    multihost_wait_for_ping compute-1 npl-private-a1 172.30.0.120
    multihost_wait_for_ping compute-1 npl-private-a1 172.30.0.50
    multihost_wait_for_ping compute-2 npl-private-b1 172.30.0.50
    multihost_wait_for_ping compute-1 npl-public1 172.30.0.110
    multihost_wait_for_ping compute-1 npl-public1 172.30.0.120
    multihost_wait_for_ping compute-1 npl-public1 10.40.0.3
    multihost_wait_for_ping compute-1 npl-public1 20.40.0.3
}

wait_for_redirect_binding() {
    local expected=$1
    local found

    for _ in {1..30}; do
        found=$(ovn-sbctl --bare --columns=_uuid find Port_Binding \
            logical_port=cr-npl-public-router-port \
            type=chassisredirect | wc -l)
        if [ "$found" -eq "$expected" ]; then
            return 0
        fi
        sleep 1
    done

    echo "Expected $expected redirect bindings, found $found" >&2
    return 1
}

run_traffic

ovn-nbctl --wait=hv lsp-set-type npl-localnet ""
wait_for_redirect_binding 1
run_traffic

ovn-nbctl --wait=hv lsp-set-type npl-localnet localnet
wait_for_redirect_binding 0
run_traffic

ovn-nbctl --wait=hv lsp-del npl-localnet
wait_for_redirect_binding 1
run_traffic
