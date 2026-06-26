#!/bin/bash
set -euo pipefail

repo_root=$(cd "$(dirname "$0")/../../.." && pwd)
cd "$repo_root"

fail=0

assert_file() {
    local path=$1
    if [ ! -f "$path" ]; then
        echo "Missing expected file: $path"
        fail=1
    fi
}

assert_contains() {
    local path=$1
    local pattern=$2
    if ! grep -R -F -q -- "$pattern" "$path"; then
        echo "Expected '$pattern' in $path"
        fail=1
    fi
}

assert_not_contains() {
    local path=$1
    local pattern=$2
    if grep -R -F -q -- "$pattern" "$path"; then
        echo "Unexpected '$pattern' in $path"
        fail=1
    fi
}

assert_file roles/distro-packages/defaults/main.yml
assert_file roles/distro-packages/tasks/main.yml

assert_contains roles/distro-packages/tasks/main.yml 'distro_package_names'
assert_contains roles/distro-packages/tasks/main.yml 'ansible_pkg_mgr == "apt"'
assert_contains roles/distro-packages/tasks/main.yml 'ansible_pkg_mgr in ["dnf", "dnf5", "yum"]'

assert_contains roles/ovn-central/defaults/main.yml 'ovn_central_package_names'
assert_contains roles/ovn-central/defaults/main.yml 'ovn_central_repository_package_names'
assert_contains roles/ovn-host/defaults/main.yml 'ovn_host_package_names'
assert_contains roles/ovn-host/defaults/main.yml 'ovn_host_repository_package_names'
assert_contains roles/ovn-install/defaults/main.yml 'ovn_distro_package_names'
assert_contains roles/ovn-install/defaults/main.yml 'ovn_distro_repository_package_names'
assert_contains roles/ovs-setup/defaults/main.yml 'ovs_package_names'
assert_contains roles/ovs-setup/defaults/main.yml 'ovs_repository_package_names'

assert_contains roles/ovn-central/tasks/main.yml 'ovn_central_package_names'
assert_contains roles/ovn-host/tasks/main.yml 'ovn_host_package_names'

assert_not_contains playbooks 'centos-release-nfv-openvswitch'
assert_not_contains playbooks 'Enable NFV SIG repo'
assert_not_contains roles 'centos-release-nfv-openvswitch'
assert_not_contains roles 'Enable NFV SIG repo'
assert_not_contains plans 'dnf install -y openvswitch'

exit "$fail"
