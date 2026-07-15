#!/bin/bash
set -euo pipefail

source "$TMT_TREE/tests/lib/assert.sh"

for cmd in ip tc ping arping modprobe ps tcpdump ethtool nft dhclient dhcpd curl wget; do
    assert_command_present "$cmd"
done

if [ -f /etc/fedora-release ]; then
    assert_command_present nc

    if [ "$(readlink -f "$(command -v nc)")" != /usr/bin/ncat ]; then
        record_failure "Fedora nc does not select /usr/bin/ncat"
    fi
fi

assert_finish
