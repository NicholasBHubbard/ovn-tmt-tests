#!/bin/bash
set -euo pipefail

source "$TMT_TREE/tests/lib/assert.sh"

assert_file /tmp/make-check-passed

assert_finish
