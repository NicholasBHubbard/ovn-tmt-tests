#!/bin/bash
set -euo pipefail

source "$TMT_TREE/tests/lib/assert.sh"

assert_command_present openssl
assert_command_present pip3
assert_command_present ps
assert_command_present tcpdump

for pkg in scapy pyftpdlib tftpy netaddr pyOpenSSL; do
    if ! pip3 show "$pkg" >/dev/null 2>&1; then
        record_failure "Expected pip package installed: $pkg"
    fi
done

assert_finish
