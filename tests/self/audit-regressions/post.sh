#!/bin/bash
set -euo pipefail

source "$TMT_TREE/tests/lib/assert.sh"
cd_repo_root

workdir=$(mktemp -d)
trap 'rm -rf "$workdir"' EXIT

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

touch "$workdir/ovn/ovn-audit.tar.gz"
if ! OVN_SOURCE_DIR="$workdir/ovn" "$TMT_TREE/tests/ovn-distcheck/post.sh"; then
    record_failure "Distcheck verifier rejected a distribution archive"
fi
rm "$workdir/ovn/ovn-audit.tar.gz"

if OVN_SOURCE_DIR="$workdir/ovn" "$TMT_TREE/tests/ovn-distcheck/post.sh" \
    > "$workdir/missing-archive.out" 2>&1; then
    record_failure "Distcheck verifier accepted a missing distribution archive"
fi

assert_file tests/ovn-dpdk/main.fmf
assert_executable tests/ovn-dpdk/post.sh
assert_contains plans/ovn-ci/system-dpdk-gcc.fmf '/tests/ovn-dpdk'
assert_contains roles/ovn_install/tasks/source.yml \
    'dest: "{{ ovn_source_dir }}/ovs/vswitchd/ovs-vswitchd"'

mkdir -p "$workdir/ovn/ovs/vswitchd"
cat > "$workdir/ovn/ovs/vswitchd/ovs-vswitchd" <<'DPDK_BINARY'
#!/bin/bash
echo "ovs-vswitchd (Open vSwitch) audit"
echo "DPDK audit"
DPDK_BINARY
chmod +x "$workdir/ovn/ovs/vswitchd/ovs-vswitchd"

if ! OVN_SOURCE_DIR="$workdir/ovn" "$TMT_TREE/tests/ovn-dpdk/post.sh"; then
    record_failure "DPDK verifier rejected a DPDK-enabled binary"
fi

cat > "$workdir/ovn/ovs/vswitchd/ovs-vswitchd" <<'NON_DPDK_BINARY'
#!/bin/bash
echo "ovs-vswitchd (Open vSwitch) audit"
NON_DPDK_BINARY

if OVN_SOURCE_DIR="$workdir/ovn" "$TMT_TREE/tests/ovn-dpdk/post.sh" \
    > "$workdir/non-dpdk.out" 2>&1; then
    record_failure "DPDK verifier accepted a binary without DPDK support"
fi

assert_contains roles/dpdk_build/defaults/main.yml 'dpdk_checksum: "sha256:'
assert_contains roles/dpdk_build/tasks/main.yml 'checksum: "{{ dpdk_checksum }}"'

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

if dpdk_output=$(ansible-playbook -i localhost, -c local \
    playbooks/dpdk-build.yml --check -e ansible_become=false \
    -e dpdk_checksum= 2>&1); then
    record_failure "DPDK role accepted an empty source checksum"
elif ! grep -F -q 'Set dpdk_checksum to the SHA-256 checksum for DPDK' \
    <<< "$dpdk_output"; then
    record_failure "DPDK role did not explain its required source checksum"
fi

if ! multihost_output=$(ansible-playbook -v -i tests/self/audit-regressions/inventory \
    playbooks/multihost.yml --check --tags topology-resolution \
    -e ansible_become=false 2>&1); then
    record_failure "Multihost inventory-name fallback failed: $multihost_output"
elif ! grep -F -q 'TASK [Resolve central address]' <<< "$multihost_output"; then
    record_failure "Multihost topology-resolution task did not run"
elif ! grep -F -q '"ovn_central_address": "central-node"' <<< "$multihost_output"; then
    record_failure "Multihost topology did not fall back to the central inventory name"
fi

if ! clustered_output=$(ansible-playbook -v -i tests/self/audit-regressions/inventory \
    playbooks/ovn-clustered.yml --check --tags topology-resolution \
    -e ansible_become=false 2>&1); then
    record_failure "Cluster inventory-name fallback failed: $clustered_output"
elif ! grep -F -q 'TASK [Build cluster member list from inventory]' <<< "$clustered_output"; then
    record_failure "Cluster topology-resolution task did not run"
elif ! grep -F -q '"ovn_cluster_members": ["leader-node", "follower-node"]' \
    <<< "$clustered_output"; then
    record_failure "Cluster topology did not fall back to inventory names"
fi

if ! multihost_output=$(ansible-playbook -v \
    -i tests/self/audit-regressions/inventory-ansible-host \
    playbooks/multihost.yml --check --tags topology-resolution \
    -e ansible_become=false 2>&1); then
    record_failure "Multihost explicit ansible_host resolution failed: $multihost_output"
elif ! grep -F -q '"ovn_central_address": "192.0.2.10"' \
    <<< "$multihost_output"; then
    record_failure "Multihost topology ignored the central ansible_host value"
fi

if ! clustered_output=$(ansible-playbook -v \
    -i tests/self/audit-regressions/inventory-ansible-host \
    playbooks/ovn-clustered.yml --check --tags topology-resolution \
    -e ansible_become=false 2>&1); then
    record_failure "Cluster explicit ansible_host resolution failed: $clustered_output"
elif ! grep -F -q \
    '"ovn_cluster_members": ["192.0.2.11", "192.0.2.12"]' \
    <<< "$clustered_output"; then
    record_failure "Cluster topology ignored explicit ansible_host values"
fi

ss() {
    if [[ "$*" == *'sport = :6641'* ]]; then
        return
    fi

    printf '%s\n' 'LISTEN 0 128 0.0.0.0:66410 0.0.0.0:*'
}

previous_failures=$ASSERT_FAILURES
ASSERT_FAILURES=0
assert_tcp_listening 6641 > "$workdir/tcp-prefix.out" 2>&1
if [ "$ASSERT_FAILURES" -eq 0 ]; then
    tcp_prefix_accepted=true
else
    tcp_prefix_accepted=false
fi
ASSERT_FAILURES=0

ss() {
    printf '%s\n' 'LISTEN 0 128 0.0.0.0:6641 0.0.0.0:*'
}

assert_tcp_listening 6641 > "$workdir/tcp-exact.out" 2>&1
if [ "$ASSERT_FAILURES" -ne 0 ]; then
    tcp_exact_rejected=true
else
    tcp_exact_rejected=false
fi
ASSERT_FAILURES=$previous_failures

if "$tcp_prefix_accepted"; then
    record_failure "TCP assertion accepted port 66410 as port 6641"
fi

if "$tcp_exact_rejected"; then
    record_failure "TCP assertion rejected the exact port 6641"
fi

unset -f ss
assert_finish
