#!/bin/bash
set -euo pipefail

podman inspect --format '{{.State.StartedAt}}' ovn-chassis-scale-b \
    > /tmp/ovn-chassis-scale-b-started
