#!/bin/bash
set -euo pipefail

source "$(dirname "$0")/../../lib/assert.sh"

assert_file /tmp/make-check-passed

assert_finish
