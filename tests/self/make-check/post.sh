#!/bin/bash
set -euo pipefail

source "$TMT_TREE/tests/lib/assert.sh"
cd_repo_root

workdir=$(mktemp -d)
trap 'rm -rf "$workdir"' EXIT

assert_file /tmp/make-check-passed

assert_contains roles/make_check/tasks/main.yml 'make_check_source_dir is defined'
assert_contains roles/make_check/tasks/main.yml "'PWD': make_check_source_dir"
assert_contains README.md 'make_check_source_dir'

if make_check_output=$(ansible-playbook -i localhost, -c local \
    playbooks/make-check.yml --check -e ansible_become=false 2>&1); then
    record_failure "Make-check role accepted a missing source directory"
elif ! grep -F -q 'Set make_check_source_dir to the configured source tree.' \
    <<< "$make_check_output"; then
    record_failure "Make-check role did not explain its required source directory"
fi

if make_check_output=$(ansible-playbook -i localhost, -c local \
    playbooks/make-check.yml --check -e ansible_become=false \
    -e make_check_source_dir= 2>&1); then
    record_failure "Make-check role accepted an empty source directory"
elif ! grep -F -q 'Set make_check_source_dir to the configured source tree.' \
    <<< "$make_check_output"; then
    record_failure "Make-check role did not explain its empty source directory"
fi

mkdir -p "$workdir/ovn/tests"
touch "$workdir/ovn/tests/system-kmod-testsuite.log"

if ! OVN_SOURCE_DIR="$workdir/ovn" \
    MAKE_CHECK_LOG=tests/system-kmod-testsuite.log \
    "$TMT_TREE/tests/ovn-make-check/post.sh"; then
    record_failure "Make-check verifier rejected the configured system-test log"
fi

if OVN_SOURCE_DIR="$workdir/ovn" \
    MAKE_CHECK_LOG=tests/missing-testsuite.log \
    "$TMT_TREE/tests/ovn-make-check/post.sh" \
    > "$workdir/missing-log.out" 2>&1; then
    record_failure "Make-check verifier accepted a missing configured log"
fi

assert_contains plans/ovn-ci/system-gcc.fmf \
    'MAKE_CHECK_LOG: tests/system-kmod-testsuite.log'
assert_contains plans/ovn-ci/system-clang-asan.fmf \
    'MAKE_CHECK_LOG: tests/system-kmod-testsuite.log'
assert_contains plans/ovn-ci/system-userspace-gcc.fmf \
    'MAKE_CHECK_LOG: tests/system-userspace-testsuite.log'
assert_contains plans/ovn-ci/system-dpdk-gcc.fmf \
    'MAKE_CHECK_LOG: tests/system-dpdk-testsuite.log'

assert_file tests/ovn-distcheck/main.fmf
assert_executable tests/ovn-distcheck/post.sh
assert_contains plans/ovn-ci/distcheck-gcc.fmf '/tests/ovn-distcheck'
assert_contains plans/ovn-ci/distcheck-gcc.fmf 'MAKE_CHECK_TESTSUITEFLAGS: "-l"'

touch "$workdir/ovn/ovn-test.tar.gz"
if ! OVN_SOURCE_DIR="$workdir/ovn" "$TMT_TREE/tests/ovn-distcheck/post.sh"; then
    record_failure "Distcheck verifier rejected a distribution archive"
fi
rm "$workdir/ovn/ovn-test.tar.gz"

if OVN_SOURCE_DIR="$workdir/ovn" "$TMT_TREE/tests/ovn-distcheck/post.sh" \
    > "$workdir/missing-archive.out" 2>&1; then
    record_failure "Distcheck verifier accepted a missing distribution archive"
fi

assert_finish
