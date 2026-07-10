#!/bin/bash
set -euo pipefail

source "$TMT_TREE/tests/lib/assert.sh"

if command -v dnf >/dev/null 2>&1; then
    dnf install -y make
elif command -v apt-get >/dev/null 2>&1; then
    apt-get update && apt-get install -y make
fi

mkdir -p /tmp/make-check-workspace
cat > /tmp/make-check-workspace/Makefile <<'MAKEFILE'
check:
	test "$(PWD)" = "/tmp/make-check-workspace"
	touch /tmp/make-check-passed
MAKEFILE

assert_file /tmp/make-check-workspace/Makefile

assert_finish
