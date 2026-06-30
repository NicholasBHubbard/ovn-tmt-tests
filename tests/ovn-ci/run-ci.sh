#!/bin/bash
set -euo pipefail

JOBS="-j$(nproc)"
export JOBS
export TIMEOUT="${TIMEOUT:-4h}"

cd /workspace/ovn
exec .ci/linux-build.sh
