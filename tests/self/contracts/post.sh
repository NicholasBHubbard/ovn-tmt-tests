#!/bin/bash
set -euo pipefail

source "$TMT_TREE/tests/lib/assert.sh"
cd_repo_root

assert_file tests/lib/assert.sh
assert_file tests/lib/ovn.sh

for test_dir in tests/self/*; do
    [ -d "$test_dir" ] || continue

    for path in "$test_dir/main.fmf" "$test_dir/pre.sh" "$test_dir/post.sh"; do
        assert_file "$path"
    done

    for path in "$test_dir/pre.sh" "$test_dir/post.sh"; do
        if [ -f "$path" ]; then
            assert_executable "$path"
            if ! grep -q -F '$TMT_TREE/tests/lib/assert.sh' "$path" && \
               ! grep -q -F '$TMT_TREE/tests/lib/ovn.sh' "$path"; then
                record_failure "$path must source assert.sh or ovn.sh from \$TMT_TREE/tests/lib/"
            fi
        fi
    done

    if [ -f "$test_dir/main.fmf" ] && ! grep -F -q 'test: ./post.sh' "$test_dir/main.fmf"; then
        record_failure "Self-test must run post.sh from main.fmf: $test_dir/main.fmf"
    fi

    test_name=${test_dir#tests/self/}
    if ! grep -R -F -q "/tests/self/$test_name" plans/self; then
        record_failure "Self-test is not referenced by any self-test plan: $test_dir"
    fi

    if ! grep -R -F -q "./tests/self/$test_name/pre.sh" plans/self; then
        record_failure "Self-test precondition is not referenced by any self-test plan: $test_dir/pre.sh"
    fi
done

if find tests/self -name main.fmf -print0 | xargs -0 grep -F -n -e 'test: ./test.sh' -e 'test: ./verify.sh' -e 'test: ./verify-topology.sh'; then
    record_failure "Self-tests must run post.sh, not legacy verifier script names."
fi

if ! grep -R -F -q '$TMT_TREE/tests/lib/ovn.sh' tests/self; then
    record_failure "At least one self-test must use tests/lib/ovn.sh."
fi

inherited_plan_dirs=(
    brew-packages
    ci
    dpdk-build
    make-check
    multihost
    ovn-central
    ovn-central-ssl
    ovn-clustered
    ovn-host
    ovn-install
    ovn-system-test-deps
    ovn-unit-test-deps
    ovs-setup
)

for plan_dir in "${inherited_plan_dirs[@]}"; do
    parent="plans/self/$plan_dir/main.fmf"
    assert_file "$parent"

    for plan in "plans/self/$plan_dir"/*.fmf; do
        [ "$plan" = "$parent" ] && continue
        if grep -q '^execute:' "$plan"; then
            record_failure "Self-test plan repeats inherited execute configuration: $plan"
        fi
        if [ "$plan_dir" != multihost ] && [ "$plan_dir" != ovn-clustered ] && \
            grep -q '^discover:' "$plan"; then
            record_failure "Self-test plan repeats inherited discover configuration: $plan"
        fi
    done
done

if find plans/self -name base.fmf -print0 | xargs -0 grep -l '^enabled: false$'; then
    record_failure "Disabled self-test parents must use main.fmf, not base.fmf."
fi

for plan in plans/ovn-ci/*.fmf; do
    [ "$plan" = plans/ovn-ci/main.fmf ] && continue
    if grep -q '^execute:' "$plan"; then
        record_failure "OVN CI plan repeats inherited execute configuration: $plan"
    fi
done

if (
    ASSERT_FAILURES=0
    ss() {
        [[ "$*" == *'sport = :6641'* ]] || \
            printf '%s\n' 'LISTEN 0 128 0.0.0.0:66410 0.0.0.0:*'
    }

    assert_tcp_listening 6641 > /dev/null 2>&1
    [ "$ASSERT_FAILURES" -eq 0 ]
); then
    record_failure "TCP assertion accepted port 66410 as port 6641"
fi

assert_finish
