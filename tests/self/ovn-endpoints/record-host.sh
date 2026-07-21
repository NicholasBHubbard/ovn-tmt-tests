#!/bin/bash
set -euo pipefail

sha256sum /etc/resolv.conf | awk '{print $1}' > /tmp/self-resolver-hash
install -D /dev/null /etc/netns/self-vm1/preserve
