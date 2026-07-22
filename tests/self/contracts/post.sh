#!/bin/bash
set -euo pipefail

source "$TMT_TREE/tests/lib/assert.sh"
cd_repo_root

assert_file tests/lib/assert.sh
assert_file tests/lib/multihost.sh
assert_file tests/lib/ovn.sh

assert_directory roles/ovn_chassis
assert_file roles/ovn_chassis/defaults/main.yml
assert_file roles/ovn_chassis/tasks/main.yml
assert_file playbooks/ovn-chassis.yml
assert_contains roles/ovn_chassis/defaults/main.yml 'ovn_chassis_instances:'
if [ -e roles/ovn_host ] || [ -e playbooks/ovn-host.yml ]; then
    record_failure "The renamed ovn_host role or playbook still exists."
fi

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
    ovn-endpoints
    ovn-chassis
    ovn-install
    ovn-system-test-deps
    ovn-topology
    ovn-unit-test-deps
    ovs-endpoints
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

multihost_parent=plans/ovn-multihost/main.fmf
assert_contains "$multihost_parent" 'playbook: playbooks/ovn-build-artifact.yml'
assert_contains "$multihost_parent" 'playbook: playbooks/multihost-driver.yml'
assert_contains "$multihost_parent" 'playbook: playbooks/multihost-driver-authorize.yml'
assert_contains "$multihost_parent" '-e ovn_install_method=artifact'
assert_contains "$multihost_parent" '-e ovn_artifact_build=$OVN_ARTIFACT_BUILD'
assert_contains "$multihost_parent" '-e ovn_artifact_expected_revision=$OVN_ARTIFACT_EXPECTED_REVISION'
assert_contains "$multihost_parent" "-e ovn_git_repo=\$OVN_GIT_REPO"
assert_contains "$multihost_parent" "-e ovn_git_version=\$OVN_GIT_VERSION"
assert_contains "$multihost_parent" 'OVN_SSL_ENABLED: "false"'
assert_contains "$multihost_parent" 'OVN_TEST_DEBUG: "false"'
assert_contains "$multihost_parent" 'playbook: playbooks/ovn-test-pki-create.yml'
assert_contains "$multihost_parent" 'playbook: playbooks/ovn-test-pki-install.yml'
assert_contains "$multihost_parent" '-e ovn_test_pki_enabled=$OVN_SSL_ENABLED'

multihost_topology_prepare=$(sed -n \
    '/  - name: Set up OVN topology/,/^$/p' "$multihost_parent")
if [[ "$multihost_topology_prepare" != *'-e ovn_ssl_enabled=$OVN_SSL_ENABLED'* ]]; then
    record_failure "OVN TLS setting is not passed to multihost topology setup"
fi

assert_file playbooks/ovn-test-pki-create.yml
assert_file playbooks/ovn-test-pki-install.yml
assert_file roles/ovn_test_pki/defaults/main.yml
assert_file roles/ovn_test_pki/tasks/create.yml
assert_file roles/ovn_test_pki/tasks/install.yml
assert_contains playbooks/multihost.yml \
    "'ssl' if ovn_ssl_enabled | default(false) | bool else 'tcp'"
assert_contains roles/ovn_central/tasks/main.yml 'del-ssl'
assert_contains roles/ovs_setup/tasks/configure.yml 'del-ssl'
assert_contains plans/self/multihost/minimal.fmf 'OVN_SSL_ENABLED: "true"'

for plan in plans/ovn-multihost/*.fmf; do
    [ "$plan" = "$multihost_parent" ] && continue
    assert_not_contains "$plan" 'playbook: playbooks/multihost.yml'
done

for test in tests/ovn-multihost-*/test.sh; do
    assert_contains "$test" 'multihost_run_playbook "$PWD/setup.yml"'
    setup=${test%/test.sh}/setup.yml
    if grep -F -q "playbook: $setup" plans/ovn-multihost/*.fmf; then
        record_failure "Test-scoped setup must not also run as plan preparation: $setup"
    fi
done

artifact_tasks=roles/ovn_install/tasks/artifact.yml
checksum_line=$(grep -n -m1 '^- name: Verify local OVN artifact checksum' "$artifact_tasks" | cut -d: -f1)
runtime_line=$(grep -n -m1 '^- name: Install DPDK runtime dependencies' "$artifact_tasks" | cut -d: -f1)
if [ "$checksum_line" -ge "$runtime_line" ]; then
    record_failure "OVN artifacts must pass checksum validation before installing runtime dependencies."
fi

artifact_manifest=$(mktemp)
artifact_file=$(mktemp)
artifact_output=$(mktemp)
trap 'rm -f "$artifact_manifest" "$artifact_file" "$artifact_output"' EXIT

run_artifact_install() {
    ansible-playbook -i localhost, -c local playbooks/ovn-install.yml \
        -e ansible_become=false \
        -e ansible_distribution=test \
        -e ansible_distribution_version=2 \
        -e ansible_architecture=test \
        -e ovn_install_method=artifact \
        -e ovn_artifact_manifest_local_path="$artifact_manifest" \
        -e ovn_artifact_local_path="$artifact_file" \
        "$@" \
        > "$artifact_output" 2>&1
}

for incompatible_host in 'wrong 2 test' 'test 1 test' 'test 2 wrong'; do
    read -r distribution distribution_version architecture <<< "$incompatible_host"
    printf '%s\n' \
        "{\"distribution\":\"$distribution\",\"distribution_version\":\"$distribution_version\",\"architecture\":\"$architecture\"}" \
        > "$artifact_manifest"

    if run_artifact_install; then
        record_failure "OVN artifact installation accepted an incompatible host."
    elif ! grep -F -q 'OVN artifact is incompatible with this host.' "$artifact_output"; then
        record_failure "OVN artifact installation did not report a compatibility failure."
    fi
done

printf '%s\n' \
    '{"distribution":"test","distribution_version":"2","architecture":"test","ovn_git_repo":"wrong","ovn_git_version":"main","ovn_revision":"revision","ovn_cc":"","ovn_configure_flags":"","ovn_make_flags":"","ovn_werror":false,"ovn_dpdk":false,"ovn_dpdk_dir":"/usr/local/dpdk","ovn_dpdk_version":"","ovn_dpdk_checksum":"","ovn_dpdk_drivers":""}' \
    > "$artifact_manifest"

if run_artifact_install; then
    record_failure "OVN artifact installation accepted incompatible build configuration."
elif ! grep -F -q 'OVN artifact build configuration does not match the request.' "$artifact_output"; then
    record_failure "OVN artifact installation did not report a build configuration failure."
fi

printf '%s\n' \
    '{"distribution":"test","distribution_version":"2","architecture":"test","ovn_git_repo":"https://github.com/ovn-org/ovn.git","ovn_git_version":"main","ovn_revision":"old","ovn_cc":"","ovn_configure_flags":"","ovn_make_flags":"","ovn_werror":false,"ovn_dpdk":false,"ovn_dpdk_dir":"/usr/local/dpdk","ovn_dpdk_version":"","ovn_dpdk_checksum":"","ovn_dpdk_drivers":"","sha256":"wrong"}' \
    > "$artifact_manifest"

if run_artifact_install -e ovn_artifact_build=false; then
    record_failure "OVN artifact reuse accepted an unspecified source revision."
elif ! grep -F -q 'Set ovn_artifact_expected_revision when reusing an OVN artifact.' "$artifact_output"; then
    record_failure "OVN artifact reuse did not require an exact source revision."
fi

if run_artifact_install -e ovn_artifact_expected_revision=new; then
    record_failure "OVN artifact installation accepted the wrong source revision."
elif ! grep -F -q 'OVN artifact source revision does not match the request.' "$artifact_output"; then
    record_failure "OVN artifact installation did not report a source revision failure."
fi

printf '%s\n' \
    '{"distribution":"test","distribution_version":"2","architecture":"test","ovn_git_repo":"https://github.com/ovn-org/ovn.git","ovn_git_version":"main","ovn_revision":"revision","ovn_cc":"","ovn_configure_flags":"","ovn_make_flags":"","ovn_werror":false,"ovn_dpdk":true,"ovn_dpdk_dir":"/usr/local/dpdk","ovn_dpdk_version":"wrong","ovn_dpdk_checksum":"wrong","ovn_dpdk_drivers":"wrong","sha256":"wrong"}' \
    > "$artifact_manifest"

if run_artifact_install \
    -e ovn_dpdk=true \
    -e ovn_dpdk_version=24.11.1 \
    -e ovn_dpdk_checksum=checksum \
    -e ovn_dpdk_drivers=drivers; then
    record_failure "OVN artifact installation accepted the wrong DPDK identity."
elif ! grep -F -q 'OVN artifact build configuration does not match the request.' "$artifact_output"; then
    record_failure "OVN artifact installation did not report a DPDK identity failure."
fi

printf '%s\n' \
    '{"distribution":"test","distribution_version":"2","architecture":"test","ovn_git_repo":"https://github.com/ovn-org/ovn.git","ovn_git_version":"main","ovn_revision":"revision","ovn_cc":"","ovn_configure_flags":"","ovn_make_flags":"","ovn_werror":false,"ovn_dpdk":false,"ovn_dpdk_dir":"/usr/local/dpdk","ovn_dpdk_version":"","ovn_dpdk_checksum":"","ovn_dpdk_drivers":"","sha256":"wrong"}' \
    > "$artifact_manifest"

if run_artifact_install; then
    record_failure "OVN artifact installation accepted a bad checksum."
elif ! grep -F -q 'OVN artifact is missing or its checksum does not match.' "$artifact_output"; then
    record_failure "OVN artifact installation did not report a checksum failure."
fi

if ansible-playbook -i localhost, -c local playbooks/ovn-build-artifact.yml \
    -e ansible_become=false \
    -e ovn_artifact_builder_hosts=all \
    -e ovn_artifact_build=false \
    -e ovn_artifact_expected_revision=revision \
    -e ovn_artifact_local_path="$artifact_file.missing" \
    -e ovn_artifact_manifest_local_path="$artifact_manifest.missing" \
    > "$artifact_output" 2>&1; then
    record_failure "OVN artifact reuse rebuilt or accepted a missing artifact."
elif ! grep -F -q 'The requested reusable OVN artifact is missing.' "$artifact_output"; then
    record_failure "OVN artifact reuse did not report a missing artifact."
fi

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
