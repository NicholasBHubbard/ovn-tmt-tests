#!/bin/bash
set -euo pipefail

source "$(dirname "$0")/../../lib/assert.sh"
cd_repo_root

assert_directory tests/self
assert_finish
