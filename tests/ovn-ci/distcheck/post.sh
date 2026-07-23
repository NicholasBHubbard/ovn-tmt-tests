#!/bin/bash
set -euo pipefail

source "$TMT_TREE/tests/lib/assert.sh"

source_dir=${OTT_SOURCE_DIR:-/usr/src/ovn}

OTT_MAKE_CHECK_TARGET=distcheck "$TMT_TREE/tests/ovn-ci/make-check/post.sh"

archives=("$source_dir"/ovn-*.tar.gz)
if [ ! -f "${archives[0]}" ]; then
    record_failure "Missing OVN distribution archive in $source_dir"
fi

assert_finish
