#!/bin/bash
set -euo pipefail

source "$TMT_TREE/tests/lib/ovn.sh"

assert_ovn_binaries_installed

assert_contains "$TMT_TREE/roles/ovn_install/tasks/git.yml" \
    'refspec: "+{{ ovn_git_version }}:refs/ovn-tmt/{{ ovn_git_version }}"'

if [ "${EXPECT_WERROR:-false}" = true ]; then
    assert_contains /usr/src/ovn/ovs/config.log "--enable-Werror"
    assert_contains /usr/src/ovn/config.log "--enable-Werror"
fi

assert_finish
