#!/bin/bash
set -euo pipefail

stat -Lc '%i' /var/run/netns/self-direct > /tmp/self-direct-ns-id
cat /sys/class/net/self-direct-p/ifindex > /tmp/self-direct-ifindex

test -s /tmp/self-direct-ns-id
test -s /tmp/self-direct-ifindex
