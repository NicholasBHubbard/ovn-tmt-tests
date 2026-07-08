#!/bin/bash
set -euo pipefail

source "$TMT_TREE/tests/lib/assert.sh"

for cmd in ip tc ping arping modprobe ps ncat tcpdump ethtool nft nfcapd nfdump dhclient dhcpd curl wget; do
    assert_command_present "$cmd"
done

assert_finish
