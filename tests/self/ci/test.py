import os

import pytest

from ovn_test.command import Runner


def selected(script, *paths):
    return Runner().output(
        script,
        input="".join(f"{path}\n" for path in paths),
    )


class TestPreconditions:
    def test_github_directory_exists(self, tree):
        assert (tree / ".github").is_dir()


class TestResult:
    @pytest.fixture(autouse=True)
    def configure_paths(self, tree):
        self.ci = tree / ".github/workflows/ci.yml"
        self.self_tests = tree / ".github/workflows/self-tests.yml"
        self.selector = tree / ".github/scripts/self-test-changes.py"

    def test_files_exist(self):
        assert self.ci.is_file()
        assert self.self_tests.is_file()
        assert self.selector.is_file()
        assert os.access(self.selector, os.X_OK)

    @pytest.mark.parametrize(
        ("expected", "paths"),
        [
            ("true", ("plans/ovn-ci/main.fmf",)),
            ("true", ("tests/build/make-check/test.py",)),
            ("true", ("components/new/config.yml",)),
            ("true", ("README.md", "roles/ovn_install/tasks/main.yml")),
            (
                "false",
                (
                    "README.md",
                    "Unified-OVN-Test-System-Proposal.md",
                    "LICENSE",
                    "LICENSE.txt",
                    "COPYING",
                    "COPYING.md",
                    ".gitignore",
                    "docs/guide.md",
                ),
            ),
            ("false", ()),
        ],
    )
    def test_change_selection(self, expected, paths):
        assert selected(self.selector, *paths) == expected

    def test_runner_and_checkout_versions(self):
        text = self.ci.read_text()

        assert "actions/checkout@v5" in text
        assert "actions/setup-python" not in text
        assert "ubuntu-26.04" in text
        assert "ubuntu-latest" not in text
        assert "ubuntu-24.04" not in text

    def test_change_detection_contract(self):
        text = self.ci.read_text()

        assert "changed: ${{ steps.self_test_changes.outputs.changed }}" in text
        assert "needs.self-test-changes.outputs.changed == 'true'" in text
        assert (
            'git diff --name-only "$base" HEAD | .github/scripts/self-test-changes.py'
        ) in text
        for output in (
            "outputs.shell",
            "outputs.yaml",
            "outputs.tmt",
            "outputs.ansible",
            "outputs.static_self_tests",
            "outputs.container_self_tests",
            "outputs.provisioned",
        ):
            assert output not in text

    def test_static_checks(self, tree):
        text = self.ci.read_text()

        for expected in (
            "name: GitHub Actions lint",
            "github.com/rhysd/actionlint/cmd/actionlint@v1.7.12",
            '"$(go env GOPATH)/bin/actionlint"',
            "apt-get install -y yamllint",
            "git ls-files -z -- '*.yaml' '*.yml' '*.fmf'",
            "xargs -0 yamllint --strict",
            "pipx install tmt",
            "tmt lint plans tests",
            "pip install ansible-lint",
            "ansible-lint --strict playbooks roles",
            "pip install ansible-core pytest pyyaml ruff==0.15.22",
            "ruff check tests",
            "ruff format --check tests",
        ):
            assert expected in text

        for obsolete in (
            "bash -n",
            "shellcheck",
            "pipx install ansible-lint",
            "ansible-playbook --syntax-check",
            "ansible-lint --profile min",
        ):
            assert obsolete not in text

        assert (tree / ".github/actionlint.yaml").is_file()
        assert (
            'label "ubuntu-26\\.04" is unknown'
            in (tree / ".github/actionlint.yaml").read_text()
        )
        assert (tree / ".yamllint").is_file()
        assert (tree / ".ansible-lint").is_file()

    def test_self_test_dispatch(self):
        ci = self.ci.read_text()
        self_tests = self.self_tests.read_text()

        assert "run-self-tests:" in ci
        assert "run-provisioned-tests:" not in ci
        assert "run-container-tests:" not in ci
        assert "container-plan:" not in ci
        assert "inputs['run-self-tests']" in ci
        assert "tmt plan ls --filter 'enabled:true'" in ci
        assert "fromJson(inputs.plans)" in self_tests
        assert "self-tests.yml" in ci

        for expected in (
            "actions/checkout@v5",
            "ansible-core",
            "ansible-galaxy collection install ansible.posix community.general",
            "podman",
            "provision-container",
            "provision-virtual",
            "fail-fast: false",
            "tmt run --all plan --name",
            "provision --feeling-safe",
        ):
            assert expected in self_tests

    def test_plan_provisioning(self, tree):
        assert "how: container" in (tree / "plans/self/ci/container.fmf").read_text()
        assert (
            "image: fedora:latest" in (tree / "plans/self/ci/container.fmf").read_text()
        )

        for relative in (
            "plans/self/contracts/base.fmf",
            "plans/self/ansible-packaging/base.fmf",
            "plans/self/ci/base.fmf",
        ):
            assert "how: local" in (tree / relative).read_text()
