#!/bin/bash
set -euo pipefail

source "$TMT_TREE/tests/lib/ovn.sh"

export PATH="/usr/local/sbin:$PATH"

assert_ovn_binaries_installed

assert_contains "$TMT_TREE/roles/ovn_install/tasks/git.yml" \
    'refspec: "+{{ ovn_git_version }}:refs/ovn-tmt/{{ ovn_git_version }}"'

if [ "${EXPECT_WERROR:-false}" = true ]; then
    assert_contains /usr/src/ovn/ovs/config.log "--enable-Werror"
    assert_contains /usr/src/ovn/config.log "--enable-Werror"
fi

if [ "${EXPECT_DPDK:-false}" = true ] && \
   ! ovs-vswitchd --version | grep -F -q 'DPDK'; then
    record_failure "Expected ovs-vswitchd to report DPDK support."
fi

assert_finish
