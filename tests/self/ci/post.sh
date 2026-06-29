#!/bin/bash
set -euo pipefail

source "$(dirname "$0")/../../lib/assert.sh"
cd_repo_root

workflow=.github/workflows/ci.yml

assert_file "$workflow"
assert_contains "$workflow" 'actions/checkout@v5'
assert_not_contains "$workflow" 'actions/setup-python'
assert_contains "$workflow" 'ubuntu-latest'
assert_not_contains "$workflow" 'ubuntu-24.04'

assert_contains "$workflow" "changed: \${{ steps.self_test_changes.outputs.changed }}"
assert_contains "$workflow" "needs.self-test-changes.outputs.changed == 'true'"
assert_not_contains "$workflow" "outputs.shell"
assert_not_contains "$workflow" "outputs.yaml"
assert_not_contains "$workflow" "outputs.tmt"
assert_not_contains "$workflow" "outputs.ansible"
assert_not_contains "$workflow" "outputs.static_self_tests"
assert_not_contains "$workflow" "outputs.container_self_tests"
assert_not_contains "$workflow" "outputs.provisioned"

assert_contains "$workflow" "*.sh"
assert_contains "$workflow" "*.bash"
assert_not_contains "$workflow" 'bash -n'
assert_contains "$workflow" 'sudo apt-get install -y shellcheck'
assert_contains "$workflow" 'shellcheck --shell=bash -x -e SC1091'
assert_contains "$workflow" '*.bash'

assert_contains "$workflow" 'apt-get install -y yamllint'
assert_contains "$workflow" 'yamllint'
assert_file .yamllint

assert_contains "$workflow" 'pipx install tmt'
assert_contains "$workflow" 'tmt lint plans tests'

assert_contains "$workflow" 'apt-get install -y ansible-core ansible-lint'
assert_not_contains "$workflow" 'ansible-playbook --syntax-check'
assert_contains "$workflow" 'ansible-lint --profile production playbooks roles'
assert_not_contains "$workflow" 'ansible-lint --profile min'

assert_contains "$workflow" 'run-self-tests:'
assert_not_contains "$workflow" 'run-provisioned-tests:'
assert_not_contains "$workflow" 'run-container-tests:'
assert_not_contains "$workflow" 'container-plan:'
assert_contains "$workflow" "inputs['run-self-tests']"
assert_contains "$workflow" 'ansible-core'
assert_contains "$workflow" 'podman'
assert_contains "$workflow" "pipx install 'tmt[all]'"
assert_contains "$workflow" "tmt run --all plan --name '/plans/self/' provision --feeling-safe"

assert_contains plans/self/ci/container.fmf 'how: container'
assert_contains plans/self/ci/container.fmf 'image: fedora:latest'

for plan in plans/self/contracts/base.fmf plans/self/ansible-packaging/base.fmf plans/self/ci/base.fmf; do
    assert_contains "$plan" 'how: local'
done

assert_finish
