#!/bin/bash
set -euo pipefail

source "$TMT_TREE/tests/lib/assert.sh"
cd_repo_root

assert_command_present ansible-playbook
assert_command_present ss

assert_finish
