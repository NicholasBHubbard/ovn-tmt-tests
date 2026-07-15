#!/bin/bash
set -uo pipefail

source_dir=${OVN_SOURCE_DIR:-/usr/src/ovn}
target=${MAKE_CHECK_TARGET:-check}
make_args=(-C "$source_dir" -j "$(nproc)" "$target")

if [ -n "${MAKE_CHECK_TESTSUITEFLAGS:-}" ]; then
    make_args+=("TESTSUITEFLAGS=$MAKE_CHECK_TESTSUITEFLAGS")
fi

status=0
make "${make_args[@]}" || status=$?

copy_status=0
(
    cd "$source_dir" || exit
    artifact_status=0
    while IFS= read -r -d '' artifact; do
        cp -a --parents "$artifact" "$TMT_TEST_DATA" || artifact_status=$?
    done < <(find . \( -type f -name '*testsuite.log' -o \
        -type d -name '*testsuite.dir' \) -print0)
    # GitHub's artifact uploader rejects sockets left by failed tests.
    find "$TMT_TEST_DATA" ! -type f ! -type d ! -type l -delete || \
        artifact_status=$?
    exit "$artifact_status"
) || copy_status=$?

if [ "$status" -eq 0 ]; then
    status=$copy_status
fi

exit "$status"
