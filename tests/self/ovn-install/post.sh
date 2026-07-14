#!/bin/bash
set -euo pipefail

source "$TMT_TREE/tests/lib/ovn.sh"

assert_ovn_binaries_installed

if [ "${EXPECT_WERROR:-false}" = true ]; then
    assert_contains /usr/src/ovn/ovs/config.log "--enable-Werror"
    assert_contains /usr/src/ovn/config.log "--enable-Werror"
fi

assert_finish
