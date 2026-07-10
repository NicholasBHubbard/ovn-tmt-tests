#!/bin/bash
set -euo pipefail

source "$TMT_TREE/tests/lib/assert.sh"

ovn_source_dir=${OVN_SOURCE_DIR:-/usr/src/ovn}
archives=("$ovn_source_dir"/ovn-*.tar.gz)

if [ ! -f "${archives[0]}" ]; then
    record_failure "Missing OVN distribution archive in $ovn_source_dir"
fi

assert_finish
