#!/bin/bash
set -euo pipefail

source "$(dirname "$0")/../../lib/assert.sh"
cd_repo_root

ci=.github/workflows/ci.yml
self_tests=.github/workflows/self-tests.yml

assert_file "$ci"
assert_file "$self_tests"

assert_contains "$ci" 'actions/checkout@v5'
assert_not_contains "$ci" 'actions/setup-python'
assert_contains "$ci" 'ubuntu-26.04'
assert_not_contains "$ci" 'ubuntu-latest'
assert_not_contains "$ci" 'ubuntu-24.04'

assert_contains "$ci" "changed: \${{ steps.self_test_changes.outputs.changed }}"
assert_contains "$ci" "needs.self-test-changes.outputs.changed == 'true'"
assert_not_contains "$ci" "outputs.shell"
assert_not_contains "$ci" "outputs.yaml"
assert_not_contains "$ci" "outputs.tmt"
assert_not_contains "$ci" "outputs.ansible"
assert_not_contains "$ci" "outputs.static_self_tests"
assert_not_contains "$ci" "outputs.container_self_tests"
assert_not_contains "$ci" "outputs.provisioned"

assert_contains "$ci" "*.sh"
assert_contains "$ci" "*.bash"
assert_not_contains "$ci" 'bash -n'
assert_contains "$ci" 'sudo apt-get install -y shellcheck'
assert_contains "$ci" 'shellcheck --severity=warning --shell=bash -x -e SC1091'
assert_contains "$ci" '*.bash'

assert_contains "$ci" 'apt-get install -y yamllint'
assert_contains "$ci" 'yamllint --strict'
assert_file .yamllint

assert_contains "$ci" 'pipx install tmt'
assert_contains "$ci" 'tmt lint plans tests'

assert_contains "$ci" 'pipx install ansible-lint'
assert_not_contains "$ci" 'ansible-playbook --syntax-check'
assert_contains "$ci" 'ansible-lint --strict --profile production playbooks roles'
assert_not_contains "$ci" 'ansible-lint --profile min'

assert_contains "$ci" 'run-self-tests:'
assert_not_contains "$ci" 'run-provisioned-tests:'
assert_not_contains "$ci" 'run-container-tests:'
assert_not_contains "$ci" 'container-plan:'
assert_contains "$ci" "inputs['run-self-tests']"
assert_contains "$ci" "tmt plan ls --filter 'enabled:true'"
assert_contains "$self_tests" "fromJson(inputs.plans)"
assert_contains "$ci" "self-tests.yml"

assert_contains "$self_tests" 'actions/checkout@v5'
assert_contains "$self_tests" 'ansible-core'
assert_contains "$self_tests" 'podman'
assert_contains "$self_tests" "provision-container"
assert_contains "$self_tests" "provision-virtual"
assert_contains "$self_tests" "fail-fast: false"
assert_contains "$self_tests" "tmt run --all plan --name"
assert_contains "$self_tests" "provision --feeling-safe"

assert_contains plans/self/ci/container.fmf 'how: container'
assert_contains plans/self/ci/container.fmf 'image: fedora:latest'

for plan in plans/self/contracts/base.fmf plans/self/ansible-packaging/base.fmf plans/self/ci/base.fmf; do
    assert_contains "$plan" 'how: local'
done

assert_finish
