#!/bin/bash
set -euo pipefail

stat -Lc '%i' /var/run/netns/self-vm1 > /tmp/self-vm1-ns-id
cat /sys/class/net/self-vm1-p/ifindex > /tmp/self-vm1-ifindex

test -s /tmp/self-vm1-ns-id
test -s /tmp/self-vm1-ifindex
