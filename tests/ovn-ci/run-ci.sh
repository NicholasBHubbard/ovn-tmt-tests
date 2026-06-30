#!/bin/bash
set -euo pipefail

exec /workspace/ovn/.ci/ci.sh \
    --ovn-path=/workspace/ovn \
    --ovs-path=/workspace/ovn/ovs \
    --jobs="$(nproc)" \
    --archive-logs
