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

workdir=$(mktemp -d)
trap 'rm -rf "$workdir"' EXIT
source_dir=$workdir/source
data_dir=$workdir/data
mkdir -p "$source_dir" "$data_dir"

cat > "$source_dir/Makefile" <<'MAKEFILE'
check:
	test "$(TESTSUITEFLAGS)" = "7-9"
	mkdir -p tests/failed-testsuite.dir
	touch tests/failed-testsuite.log
	touch tests/failed-testsuite.dir/details.log
	chmod 700 tests/failed-testsuite.dir
	chmod 600 tests/failed-testsuite.log tests/failed-testsuite.dir/details.log
	false

distcheck:
	test "$(PWD)" = "$(CURDIR)"
	touch ovn-fixture.tar.gz
MAKEFILE

if TMT_TEST_DATA=$data_dir \
    OVN_SOURCE_DIR=$source_dir \
    MAKE_CHECK_TESTSUITEFLAGS=7-9 \
    ./tests/ovn-make-check/post.sh; then
    make_status=0
else
    make_status=$?
fi

if [ "$make_status" -ne 2 ]; then
    record_failure "OVN make workload returned $make_status instead of make status 2"
fi

assert_file "$data_dir/tests/failed-testsuite.log"
assert_directory "$data_dir/tests/failed-testsuite.dir"
assert_file "$data_dir/tests/failed-testsuite.dir/details.log"

if unreadable_file=$(find "$data_dir" -type f ! -perm -0444 -print -quit) &&
    [ -n "$unreadable_file" ]; then
    record_failure "Copied artifact is not readable by the artifact uploader: $unreadable_file"
fi

if inaccessible_dir=$(find "$data_dir" -type d ! -perm -0555 -print -quit) &&
    [ -n "$inaccessible_dir" ]; then
    record_failure "Copied artifact directory is not traversable by the artifact uploader: $inaccessible_dir"
fi

if grep -R -F -q 'playbooks/make-check.yml' plans/ovn-ci; then
    record_failure "OVN CI plans still run make check during prepare"
fi

assert_contains plans/ovn-ci/main.fmf \
    'OVN_GIT_REPO: https://github.com/ovn-org/ovn.git'
assert_contains plans/ovn-ci/main.fmf 'OVN_GIT_VERSION: main'
assert_contains plans/ovn-ci/main.fmf \
    '-e ovn_git_repo=$OVN_GIT_REPO -e ovn_git_version=$OVN_GIT_VERSION'
assert_contains plans/ovn-ci/main.fmf \
    "-e 'ovn_configure_flags=\$OVN_CONFIGURE_FLAGS'"

if ! TMT_TEST_DATA=$data_dir \
    OVN_SOURCE_DIR=$source_dir \
    ./tests/ovn-distcheck/post.sh; then
    record_failure "OVN distcheck workload did not produce its archive"
fi

assert_finish
