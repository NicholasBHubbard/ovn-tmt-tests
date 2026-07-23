#!/bin/bash
set -euo pipefail

source "$TMT_TREE/tests/lib/assert.sh"
cd_repo_root

assert_file tests/lib/assert.sh
assert_file tests/lib/multihost.sh
assert_file tests/lib/ovn.sh
assert_file tools/check-naming.py

naming_tree=$(mktemp -d)
mkdir -p "$naming_tree/plans" "$naming_tree/roles/example/defaults"
printf '%s\n' 'example: []' \
    > "$naming_tree/roles/example/defaults/main.yaml"
printf '%s\n' 'environment:' '  OTT_EXAMPLE: value' \
    > "$naming_tree/plans/main.fmf"
if ! python3 tools/check-naming.py "$naming_tree" > /dev/null; then
    record_failure "Naming checker rejected valid names."
fi

printf '%s\n' 'wrong_name: true' \
    > "$naming_tree/roles/example/defaults/main.yaml"
if [ -f tools/check-naming.py ] && \
   python3 tools/check-naming.py "$naming_tree" > /dev/null 2>&1; then
    record_failure "Naming checker accepted an incorrectly prefixed role variable."
fi

printf '%s\n' 'example: []' \
    > "$naming_tree/roles/example/defaults/main.yaml"
printf '%s\n' 'environment:' '  WRONG_NAME: value' \
    > "$naming_tree/plans/main.fmf"
if python3 tools/check-naming.py "$naming_tree" > /dev/null 2>&1; then
    record_failure "Naming checker accepted an incorrectly prefixed environment variable."
fi

if python3 tools/check-naming.py "$naming_tree/missing" > /dev/null 2>&1; then
    record_failure "Naming checker accepted a missing repository root."
fi
rm -rf "$naming_tree"

if ! python3 tools/check-naming.py "$TMT_TREE"; then
    record_failure "Repository naming convention failed."
fi

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
assert_contains "$multihost_parent" '-e ovn_artifact_build=$OTT_ARTIFACT_BUILD'
assert_contains "$multihost_parent" '-e ovn_artifact_expected_revision=$OTT_ARTIFACT_EXPECTED_REVISION'
assert_contains "$multihost_parent" "-e ovn_install_git_repo=\$OTT_GIT_REPO"
assert_contains "$multihost_parent" "-e ovn_install_git_version=\$OTT_GIT_VERSION"
assert_contains "$multihost_parent" 'OTT_SSL_ENABLED: "false"'
assert_contains "$multihost_parent" 'OTT_TEST_DEBUG: "false"'
assert_contains "$multihost_parent" 'playbook: playbooks/ovn-test-pki-create.yml'
assert_contains "$multihost_parent" 'playbook: playbooks/ovn-test-pki-install.yml'
assert_contains "$multihost_parent" '-e ovn_test_pki_enabled=$OTT_SSL_ENABLED'

multihost_topology_prepare=$(sed -n \
    '/  - name: Set up OVN topology/,/^$/p' "$multihost_parent")
if [[ "$multihost_topology_prepare" != *'-e ovn_multihost_ssl_enabled=$OTT_SSL_ENABLED'* ]]; then
    record_failure "OVN TLS setting is not passed to multihost topology setup"
fi

assert_file playbooks/ovn-test-pki-create.yml
assert_file playbooks/ovn-test-pki-install.yml
assert_file roles/ovn_test_pki/defaults/main.yml
assert_file roles/ovn_test_pki/tasks/create.yml
assert_file roles/ovn_test_pki/tasks/install.yml
assert_contains playbooks/multihost.yml \
    'if ovn_multihost_ssl_enabled | default(false) | bool'
assert_contains roles/ovn_central/tasks/main.yml 'del-ssl'
assert_contains roles/ovs_setup/tasks/configure.yml 'del-ssl'
assert_contains plans/self/multihost/minimal.fmf 'OTT_SSL_ENABLED: "true"'

for plan in plans/ovn-multihost/*.fmf; do
    [ "$plan" = "$multihost_parent" ] && continue
    assert_not_contains "$plan" 'playbook: playbooks/multihost.yml'
done

for test in tests/ovn-fake-multinode/*/test.sh; do
    [ "$test" = tests/ovn-fake-multinode/gateway-nat/test.sh ] && continue
    assert_contains "$test" 'multihost_run_playbook "$PWD/setup.yml"'
    setup=${test%/test.sh}/setup.yml
    if grep -F -q "playbook: $setup" plans/ovn-multihost/*.fmf; then
        record_failure "Test-scoped setup must not also run as plan preparation: $setup"
    fi
done

assert_directory roles/ovn_artifact
assert_file roles/ovn_artifact/defaults/main.yml
assert_file roles/ovn_artifact/tasks/main.yml
assert_file roles/ovn_artifact/tasks/build.yml
assert_file roles/ovn_artifact/tasks/validate.yml
assert_contains playbooks/ovn-build-artifact.yml '- role: ovn_artifact'
assert_not_contains playbooks/ovn-build-artifact.yml \
    '- name: Create OVN artifact'
assert_contains roles/ovn_install/tasks/artifact.yml 'name: ovn_artifact'
assert_contains roles/ovn_install/tasks/artifact.yml \
    'ovn_artifact_action: validate'
artifact_install_tasks=roles/ovn_install/tasks/artifact.yml
validation_line=$(grep -n -m1 '^- name: Validate OVN artifact' \
    "$artifact_install_tasks" | cut -d: -f1)
runtime_line=$(grep -n -m1 '^- name: Install DPDK runtime dependencies' \
    "$artifact_install_tasks" | cut -d: -f1)
if [ -n "$validation_line" ] && [ -n "$runtime_line" ] && \
   [ "$validation_line" -ge "$runtime_line" ]; then
    record_failure "OVN artifacts must be validated before installing runtime dependencies."
fi
assert_contains roles/ovn_artifact/tasks/validate.yml \
    '- name: Verify local OVN artifact checksum'
assert_contains roles/ovn_artifact/tasks/validate.yml \
    'ovn_artifact_identity:'

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

run_artifact_validation() {
    ansible-playbook -i localhost, -c local \
        tests/self/contracts/validate-artifact.yml \
        -e ansible_become=false \
        -e ovn_artifact_expected_distribution=test \
        -e ovn_artifact_expected_distribution_version=2 \
        -e ovn_artifact_expected_architecture=test \
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
    -e ovn_install_dpdk_enabled=true \
    -e ovn_install_dpdk_version=24.11.1 \
    -e ovn_install_dpdk_checksum=checksum \
    -e ovn_install_dpdk_drivers=drivers; then
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

artifact_checksum=$(sha256sum "$artifact_file" | cut -d ' ' -f1)
printf '%s\n' \
    "{\"distribution\":\"test\",\"distribution_version\":\"2\",\"architecture\":\"test\",\"ovn_git_repo\":\"https://github.com/ovn-org/ovn.git\",\"ovn_git_version\":\"main\",\"ovn_revision\":\"revision\",\"ovn_cc\":\"\",\"ovn_configure_flags\":\"\",\"ovn_make_flags\":\"\",\"ovn_werror\":false,\"ovn_dpdk\":false,\"ovn_dpdk_dir\":\"/usr/local/dpdk\",\"ovn_dpdk_version\":\"\",\"ovn_dpdk_checksum\":\"\",\"ovn_dpdk_drivers\":\"\",\"sha256\":\"$artifact_checksum\"}" \
    > "$artifact_manifest"

if ! run_artifact_validation; then
    record_failure "A non-installing consumer could not validate an OVN artifact."
fi

if run_artifact_validation -e ovn_artifact_action=invalid; then
    record_failure "OVN artifact role accepted an invalid action."
elif ! grep -F -q 'ovn_artifact_action must be build or validate.' "$artifact_output"; then
    record_failure "OVN artifact role did not report an invalid action."
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

scale_plan=plans/ovn-multihost/scale-density-light.fmf
scale_test=tests/ovn-scale/density-light/test.sh
assert_file "$scale_plan"
assert_file tests/ovn-scale/density-light/main.fmf
assert_file "$scale_test"
assert_executable "$scale_test"
assert_contains "$scale_plan" 'environment+:'
assert_contains "$scale_plan" 'OTT_SCALE_INITIAL_PORTS:'
assert_contains "$scale_plan" 'OTT_SCALE_ITERATIONS:'
assert_contains "$scale_plan" 'OTT_SCALE_TIMEOUT:'
assert_contains "$scale_plan" 'OTT_SCALE_IPV4:'
assert_contains "$scale_plan" 'OTT_SCALE_IPV6:'
assert_contains "$scale_plan" 'OTT_SCALE_MTU:'
assert_contains "$scale_plan" '/tests/ovn-scale/density-light'
assert_contains "$scale_test" 'ovn-nbctl --wait=hv'
assert_contains "$scale_test" 'metrics.csv'
assert_contains "$scale_test" 'scale_cleanup'
scale_tracking_line=$(grep -n -m1 'SCALE_ENDPOINT_GUESTS\[index\]=' \
    "$scale_test" | cut -d: -f1)
scale_mutation_line=$(grep -n -m1 'ovn-nbctl --may-exist lsp-add' \
    "$scale_test" | cut -d: -f1)
if [ -n "$scale_tracking_line" ] && [ -n "$scale_mutation_line" ] && \
   [ "$scale_tracking_line" -ge "$scale_mutation_line" ]; then
    record_failure "Scale cleanup must track an endpoint before creating it."
fi

if [ -f "$scale_test" ]; then
    # shellcheck disable=SC1090
    source "$scale_test"

    if ! scale_validate_config 2 1 60 true false 2; then
        record_failure "Valid scale workload configuration was rejected."
    fi
    if ! scale_validate_config 2 1 60 false true 2; then
        record_failure "Valid IPv6-only scale workload configuration was rejected."
    fi
    if ! scale_validate_config 65533 1 60 true true 2; then
        record_failure "The scale workload rejected its address-space boundary."
    fi
    if scale_validate_config 1 1 60 true true 2; then
        record_failure "Scale workload accepted fewer initial ports than chassis."
    fi
    if scale_validate_config 2 0 60 true true 2; then
        record_failure "Scale workload accepted zero measured iterations."
    fi
    if scale_validate_config 2 1 60 false false 2; then
        record_failure "Scale workload accepted both IP families being disabled."
    fi
    if scale_validate_config 2 1 60 maybe true 2; then
        record_failure "Scale workload accepted an invalid boolean."
    fi
    if scale_validate_config 2 1 0 true true 2; then
        record_failure "Scale workload accepted a zero timeout."
    fi
    if scale_validate_config 2 1 60 true true 1; then
        record_failure "Scale workload accepted fewer than two chassis."
    fi
    if scale_validate_config 65534 1 60 true true 2; then
        record_failure "Scale workload accepted more endpoints than its address space."
    fi
    if scale_validate_config 18446744073709551618 1 60 true true 2; then
        record_failure "Scale workload accepted an overflowing endpoint count."
    fi
    if ! scale_validate_mtu 576 false || scale_validate_mtu 575 false || \
       ! scale_validate_mtu 1280 true || scale_validate_mtu 1279 true || \
       ! scale_validate_mtu 65535 true || scale_validate_mtu 65536 true || \
       scale_validate_mtu 18446744073709552192 false || \
       scale_validate_mtu invalid false; then
        record_failure "Scale workload MTU boundaries are incorrect."
    fi

    if [ "$(scale_endpoint_name 0)" != dl00000 ] || \
       [ "$(scale_host_interface 0)" != dl00000-p ] || \
       [ "$(scale_mac 0)" != 02:00:00:00:00:01 ] || \
       [ "$(scale_ipv4 0)" != 10.240.0.1 ] || \
       [ "$(scale_ipv6 0)" != fd00:240::1 ]; then
        record_failure "Scale endpoint identity is not deterministic."
    fi
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
