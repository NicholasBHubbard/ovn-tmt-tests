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
	false

distcheck:
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

if grep -R -F -q 'playbooks/make-check.yml' plans/ovn-ci; then
    record_failure "OVN CI plans still run make check during prepare"
fi

if ! TMT_TEST_DATA=$data_dir \
    OVN_SOURCE_DIR=$source_dir \
    ./tests/ovn-distcheck/post.sh; then
    record_failure "OVN distcheck workload did not produce its archive"
fi

assert_finish
