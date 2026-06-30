#!/bin/bash
set -euo pipefail

source "$(dirname "$0")/../../lib/assert.sh"

dnf install -y make

mkdir -p /tmp/make-check-workspace
cat > /tmp/make-check-workspace/Makefile <<'MAKEFILE'
check:
	touch /tmp/make-check-passed
MAKEFILE

assert_file /tmp/make-check-workspace/Makefile

assert_finish
