#!/bin/bash
set -euo pipefail

source "$TMT_TREE/tests/lib/assert.sh"
cd_repo_root

assert_file roles/distro_packages/defaults/main.yml
assert_file roles/distro_packages/tasks/main.yml

assert_contains roles/distro_packages/tasks/main.yml 'distro_package_names'
assert_contains roles/distro_packages/tasks/main.yml 'ansible_facts["pkg_mgr"] == "apt"'
assert_contains roles/distro_packages/tasks/main.yml 'ansible_facts["pkg_mgr"] in ["apt", "dnf", "dnf5", "yum", "homebrew"]'

assert_contains roles/ovn_install/defaults/main.yml 'ovn_distro_package_names'
assert_contains roles/ovn_install/defaults/main.yml 'ovn_distro_repository_package_names'
assert_contains roles/ovs_setup/defaults/main.yml 'ovs_package_names'
assert_contains roles/ovs_setup/defaults/main.yml 'ovs_repository_package_names'

assert_not_contains roles/ovn_central/tasks/main.yml 'distro_packages'
assert_not_contains roles/ovn_central/defaults/main.yml 'ovn_central_package_names'
assert_not_contains roles/ovn_chassis/tasks/main.yml 'distro_packages'
assert_not_contains roles/ovn_chassis/defaults/main.yml 'ovn_chassis_package_names'

assert_contains playbooks/ovn-central.yml 'ovn_install'
assert_contains playbooks/ovn-central.yml 'ovs_setup'
assert_contains playbooks/ovn-chassis.yml 'ovn_install'
assert_contains playbooks/ovn-chassis.yml 'ovs_setup'
assert_contains playbooks/multihost.yml 'ovn_install'
assert_contains playbooks/multihost.yml 'ovs_setup'

assert_not_contains playbooks 'centos-release-nfv-openvswitch'
assert_not_contains playbooks 'Enable NFV SIG repo'
assert_not_contains roles 'centos-release-nfv-openvswitch'
assert_not_contains roles 'Enable NFV SIG repo'
assert_not_contains plans 'dnf install -y openvswitch'

assert_finish
