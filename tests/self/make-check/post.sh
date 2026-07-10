#!/bin/bash
set -euo pipefail

source "$TMT_TREE/tests/lib/assert.sh"
cd_repo_root

assert_file /tmp/make-check-passed

if make_check_output=$(ansible-playbook -i localhost, -c local \
    playbooks/make-check.yml --check -e ansible_become=false 2>&1); then
    record_failure "Make-check role accepted a missing source directory"
elif ! grep -F -q 'Set make_check_source_dir to the configured source tree.' \
    <<< "$make_check_output"; then
    record_failure "Make-check role did not explain its required source directory"
fi

assert_finish
