#!/bin/bash
set -euo pipefail

source "$TMT_TREE/tests/lib/assert.sh"
cd_repo_root

workdir=$(mktemp -d)
trap 'rm -rf "$workdir"' EXIT

assert_directory /usr/local/dpdk
assert_file /usr/local/dpdk/lib64/pkgconfig/libdpdk.pc

assert_file tests/ovn-dpdk/main.fmf
assert_executable tests/ovn-dpdk/post.sh
assert_contains plans/ovn-ci/system-dpdk-gcc.fmf '/tests/ovn-dpdk'
assert_contains roles/ovn_install/tasks/source.yml \
    'dest: "{{ ovn_source_dir }}/ovs/vswitchd/ovs-vswitchd"'
assert_contains roles/dpdk_build/defaults/main.yml 'dpdk_checksum: "sha256:'
assert_contains roles/dpdk_build/tasks/main.yml 'checksum: "{{ dpdk_checksum }}"'

mkdir -p "$workdir/ovn/ovs/vswitchd"
cat > "$workdir/ovn/ovs/vswitchd/ovs-vswitchd" <<'DPDK_BINARY'
#!/bin/bash
echo "ovs-vswitchd (Open vSwitch) test"
echo "DPDK test"
DPDK_BINARY
chmod +x "$workdir/ovn/ovs/vswitchd/ovs-vswitchd"

if ! OVN_SOURCE_DIR="$workdir/ovn" "$TMT_TREE/tests/ovn-dpdk/post.sh"; then
    record_failure "DPDK verifier rejected a DPDK-enabled binary"
fi

cat > "$workdir/ovn/ovs/vswitchd/ovs-vswitchd" <<'NON_DPDK_BINARY'
#!/bin/bash
echo "ovs-vswitchd (Open vSwitch) test"
NON_DPDK_BINARY

if OVN_SOURCE_DIR="$workdir/ovn" "$TMT_TREE/tests/ovn-dpdk/post.sh" \
    > "$workdir/non-dpdk.out" 2>&1; then
    record_failure "DPDK verifier accepted a binary without DPDK support"
fi

if dpdk_output=$(ansible-playbook -i localhost, -c local \
    playbooks/dpdk-build.yml --check -e ansible_become=false \
    -e dpdk_checksum= 2>&1); then
    record_failure "DPDK role accepted an empty source checksum"
elif ! grep -F -q 'Set dpdk_checksum to the SHA-256 checksum for DPDK' \
    <<< "$dpdk_output"; then
    record_failure "DPDK role did not explain its required source checksum"
fi

assert_finish
