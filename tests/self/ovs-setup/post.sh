#!/bin/bash
set -euo pipefail

source "$TMT_TREE/tests/lib/assert.sh"
source "$TMT_TREE/tests/lib/ovn.sh"
cd_repo_root

assert_contains roles/ovs_setup/tasks/git.yml \
    'refspec: "+{{ ovs_setup_git_version }}:refs/ovs-tmt/{{ ovs_setup_git_version }}"'

echo "Checking ovs-vsctl..."
assert_ovs_configured

echo "Checking OVS binaries are in PATH..."
assert_command_present ovs-vswitchd
assert_command_present ovsdb-server

echo "Checking OVS processes..."
assert_process_present ovsdb-server
assert_process_present ovs-vswitchd

assert_finish
