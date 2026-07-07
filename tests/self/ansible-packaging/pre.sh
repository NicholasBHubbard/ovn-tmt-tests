#!/bin/bash
set -euo pipefail

source "$TMT_TREE/tests/lib/assert.sh"
cd_repo_root

assert_directory roles
assert_directory playbooks
assert_directory plans
assert_finish
