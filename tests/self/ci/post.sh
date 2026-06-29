#!/bin/bash
set -euo pipefail

source "$(dirname "$0")/../../lib/assert.sh"
cd_repo_root

workflow=.github/workflows/ci.yml

assert_file "$workflow"
assert_contains "$workflow" 'actions/checkout@v5'
assert_contains "$workflow" 'actions/setup-python@v6'
assert_contains "$workflow" 'changes:'
assert_contains "$workflow" 'git diff --name-only'
assert_contains "$workflow" "shell: \${{ steps.changed.outputs.shell }}"
assert_contains "$workflow" "tmt: \${{ steps.changed.outputs.tmt }}"
assert_contains "$workflow" "ansible: \${{ steps.changed.outputs.ansible }}"
assert_contains "$workflow" "static-self-tests: \${{ steps.changed.outputs.static_self_tests }}"
assert_contains "$workflow" "container-self-tests: \${{ steps.changed.outputs.container_self_tests }}"
assert_contains "$workflow" 'needs: changes'
assert_contains "$workflow" "if: needs.changes.outputs.shell == 'true'"
assert_contains "$workflow" "if: needs.changes.outputs.tmt == 'true'"
assert_contains "$workflow" "if: needs.changes.outputs.ansible == 'true'"
assert_contains "$workflow" "if: needs.changes.outputs.static_self_tests == 'true'"
assert_contains "$workflow" "needs.changes.outputs.container_self_tests == 'true'"
assert_contains "$workflow" "\\( -name '*.sh' -o -name '*.bash' \\)"
assert_contains "$workflow" 'bash -n'
assert_contains "$workflow" 'sudo apt-get install -y shellcheck'
assert_contains "$workflow" 'shellcheck --shell=bash -x -e SC1091'
assert_not_contains "$workflow" ")$'"
assert_contains "$workflow" '*.bash'
assert_contains "$workflow" 'tmt lint plans tests'
assert_contains "$workflow" "yaml: \${{ steps.changed.outputs.yaml }}"
assert_contains "$workflow" "if: needs.changes.outputs.yaml == 'true'"
assert_contains "$workflow" 'pip install yamllint'
assert_contains "$workflow" 'yamllint'
assert_file .yamllint
assert_contains "$workflow" 'ansible-playbook --syntax-check'
assert_contains "$workflow" 'ansible-lint --profile production playbooks roles'
assert_not_contains "$workflow" 'ansible-lint --profile min'
assert_contains "$workflow" './tests/self/contracts/post.sh'
assert_contains "$workflow" './tests/self/ansible-packaging/post.sh'
assert_contains "$workflow" './tests/self/ci/post.sh'
assert_contains "$workflow" "tmt run --all plan --name '/plans/self/(contracts|ansible-packaging|ci)/base' provision --feeling-safe"
assert_contains "$workflow" 'run-container-tests:'
assert_contains "$workflow" 'container-plan:'
assert_contains "$workflow" "inputs['run-container-tests']"
assert_contains "$workflow" "inputs['container-plan']"
assert_contains "$workflow" 'sudo apt-get install -y podman'
assert_contains "$workflow" "python -m pip install 'tmt[provision-container]'"
assert_contains "$workflow" "tmt run --all plan --name \"\$TMT_PLAN\""

assert_contains plans/self/ci/container.fmf 'how: container'
assert_contains plans/self/ci/container.fmf 'image: fedora:latest'

for plan in plans/self/contracts/base.fmf plans/self/ansible-packaging/base.fmf plans/self/ci/base.fmf; do
    assert_contains "$plan" 'how: local'
done

assert_finish
