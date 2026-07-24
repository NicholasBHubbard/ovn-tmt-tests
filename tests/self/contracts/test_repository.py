import pytest
import yaml

from ovn_test.command import Runner
from ovn_test.files import find_text


INHERITED_SELF_PLANS = (
    "brew-packages",
    "ci",
    "dpdk-build",
    "make-check",
    "multihost",
    "ovn-central",
    "ovn-central-ssl",
    "ovn-clustered",
    "ovn-endpoints",
    "ovn-chassis",
    "ovn-install",
    "ovn-system-test-deps",
    "ovn-topology",
    "ovn-unit-test-deps",
    "ovs-endpoints",
    "ovs-setup",
)


def content(tree, path):
    return (tree / path).read_text()


def assert_contains(tree, path, expected):
    assert expected in content(tree, path), path


def run_naming(tree, root):
    return Runner().run(
        "python3",
        tree / "tools/check-naming.py",
        root,
        check=False,
    )


class TestPreconditions:
    def test_self_test_directory_exists(self, tree):
        assert (tree / "tests/self").is_dir()


class TestNaming:
    def test_valid_names(self, tree, tmp_path):
        defaults = tmp_path / "roles/example/defaults"
        plans = tmp_path / "plans"
        defaults.mkdir(parents=True)
        plans.mkdir()
        (defaults / "main.yaml").write_text("example: []\n")
        (plans / "main.fmf").write_text("environment:\n  OTT_EXAMPLE: value\n")

        assert run_naming(tree, tmp_path).returncode == 0

    def test_invalid_role_variable(self, tree, tmp_path):
        defaults = tmp_path / "roles/example/defaults"
        defaults.mkdir(parents=True)
        (tmp_path / "plans").mkdir()
        (defaults / "main.yaml").write_text("wrong_name: true\n")

        assert run_naming(tree, tmp_path).returncode != 0

    def test_invalid_environment_variable(self, tree, tmp_path):
        defaults = tmp_path / "roles/example/defaults"
        plans = tmp_path / "plans"
        defaults.mkdir(parents=True)
        plans.mkdir()
        (defaults / "main.yaml").write_text("example: []\n")
        (plans / "main.fmf").write_text("environment:\n  WRONG_NAME: value\n")

        assert run_naming(tree, tmp_path).returncode != 0

    def test_missing_root(self, tree, tmp_path):
        assert run_naming(tree, tmp_path / "missing").returncode != 0

    def test_repository_names(self, tree):
        assert run_naming(tree, tree).returncode == 0


def test_every_self_test_is_referenced_by_a_plan(tree):
    plans = tree / "plans/self"
    for test_dir in (tree / "tests/self").iterdir():
        if not test_dir.is_dir() or test_dir.name.startswith((".", "__")):
            continue
        assert (test_dir / "main.fmf").is_file()
        assert list(test_dir.glob("test*.py"))
        assert find_text(plans, f"/tests/self/{test_dir.name}")


def test_pytest_prepare_phases_run_after_test_dependencies(tree):
    for path in (tree / "plans/self").rglob("*.fmf"):
        prepare = (yaml.safe_load(path.read_text()) or {}).get("prepare", [])
        previous = None
        for phase in prepare:
            if "python3 -m pytest" in phase.get("script", ""):
                assert phase.get("order", 50) > 70, path
                previous = phase["order"]
            elif previous is not None:
                assert phase.get("order", 50) > previous, path
                previous = phase["order"]


@pytest.mark.parametrize("plan_dir", INHERITED_SELF_PLANS)
def test_self_test_children_inherit_common_steps(tree, plan_dir):
    directory = tree / "plans/self" / plan_dir
    parent = directory / "main.fmf"
    assert parent.is_file()
    for plan in directory.glob("*.fmf"):
        if plan == parent:
            continue
        text = plan.read_text()
        assert "\nexecute:" not in f"\n{text}"
        if plan_dir not in {"multihost", "ovn-clustered"}:
            assert "\ndiscover:" not in f"\n{text}"


def test_disabled_self_test_parents_use_main_metadata(tree):
    for path in (tree / "plans/self").rglob("base.fmf"):
        assert "\nenabled: false\n" not in f"\n{path.read_text()}\n"


def test_ovn_ci_children_inherit_execution(tree):
    directory = tree / "plans/ovn-ci"
    for plan in directory.glob("*.fmf"):
        if plan.name != "main.fmf":
            assert "\nexecute:" not in f"\n{plan.read_text()}"


def test_multihost_parent_propagates_configuration(tree):
    path = "plans/ovn-multihost/main.fmf"
    expected = (
        "playbook: playbooks/ovn-build-artifact.yml",
        "playbook: playbooks/multihost-driver.yml",
        "playbook: playbooks/multihost-driver-authorize.yml",
        "-e ovn_install_method=artifact",
        "-e ovn_artifact_build=$OTT_ARTIFACT_BUILD",
        "-e ovn_artifact_expected_revision=$OTT_ARTIFACT_EXPECTED_REVISION",
        "-e ovn_install_git_repo=$OTT_GIT_REPO",
        "-e ovn_install_git_version=$OTT_GIT_VERSION",
        'OTT_SSL_ENABLED: "false"',
        'OTT_TEST_DEBUG: "false"',
        "playbook: playbooks/ovn-test-pki-create.yml",
        "playbook: playbooks/ovn-test-pki-install.yml",
        "-e ovn_test_pki_enabled=$OTT_SSL_ENABLED",
        "-e ovn_multihost_ssl_enabled=$OTT_SSL_ENABLED",
    )
    for value in expected:
        assert_contains(tree, path, value)
    assert_contains(tree, path, "enabled: false")


def test_multihost_tls_contract(tree):
    paths = (
        "playbooks/ovn-test-pki-create.yml",
        "playbooks/ovn-test-pki-install.yml",
        "roles/ovn_test_pki/defaults/main.yml",
        "roles/ovn_test_pki/tasks/create.yml",
        "roles/ovn_test_pki/tasks/install.yml",
    )
    assert all((tree / path).is_file() for path in paths)
    assert_contains(
        tree,
        "playbooks/multihost.yml",
        "if ovn_multihost_ssl_enabled | default(false) | bool",
    )
    assert_contains(tree, "roles/ovn_central/tasks/main.yml", "del-ssl")
    assert_contains(tree, "roles/ovs_setup/tasks/configure.yml", "del-ssl")
    assert_contains(
        tree,
        "plans/self/multihost/minimal.fmf",
        'OTT_SSL_ENABLED: "true"',
    )


def test_multihost_children_inherit_base(tree):
    parent = tree / "plans/ovn-multihost/main.fmf"
    for plan in parent.parent.rglob("*.fmf"):
        if plan.name == "main.fmf":
            continue
        assert "playbook: playbooks/multihost.yml" not in plan.read_text()
        assert "enabled: true" in plan.read_text()


def test_multihost_setup_is_test_scoped(tree):
    plans = "\n".join(
        path.read_text() for path in (tree / "plans/ovn-multihost").rglob("*.fmf")
    )
    for setup in (tree / "tests/multihost").glob("*/setup.yml"):
        if setup.parent.name == "gateway-nat":
            continue
        test = setup.with_name("test.py")
        assert test.is_file()
        assert 'pytest.mark.usefixtures("setup_scenario")' in test.read_text()
        assert str(setup).removeprefix(f"{tree}/") not in plans


def test_artifact_role_contract(tree):
    paths = (
        "roles/ovn_artifact/defaults/main.yml",
        "roles/ovn_artifact/tasks/main.yml",
        "roles/ovn_artifact/tasks/build.yml",
        "roles/ovn_artifact/tasks/validate.yml",
    )
    assert all((tree / path).is_file() for path in paths)
    assert_contains(tree, "playbooks/ovn-build-artifact.yml", "- role: ovn_artifact")
    assert "- name: Create OVN artifact" not in content(
        tree, "playbooks/ovn-build-artifact.yml"
    )
    install = content(tree, "roles/ovn_install/tasks/artifact.yml")
    assert "name: ovn_artifact" in install
    assert "ovn_artifact_action: validate" in install
    assert install.index("- name: Validate OVN artifact") < install.index(
        "- name: Install DPDK runtime dependencies"
    )
    validate = content(tree, "roles/ovn_artifact/tasks/validate.yml")
    assert "- name: Verify local OVN artifact checksum" in validate
    assert "ovn_artifact_identity:" in validate


@pytest.mark.parametrize(
    ("plan", "test", "settings"),
    [
        (
            "density-light.fmf",
            "density-light",
            (
                "OTT_SCALE_INITIAL_PORTS:",
                "OTT_SCALE_ITERATIONS:",
            ),
        ),
        (
            "density-heavy.fmf",
            "density-heavy",
            (
                "OTT_SCALE_INITIAL_PODS:",
                "OTT_SCALE_ITERATIONS:",
                "OTT_SCALE_PODS_PER_SERVICE:",
                "OTT_SCALE_LB_PROTOCOLS:",
            ),
        ),
    ],
)
def test_scale_workload_contract(tree, plan, test, settings):
    plan_path = tree / "plans/ovn-multihost/ovn-scale-testing" / plan
    test_dir = tree / "tests/scale" / test
    assert plan_path.is_file()
    assert (test_dir / "main.fmf").is_file()
    assert (test_dir / "test.py").is_file()
    for setting in settings:
        assert setting in plan_path.read_text()
    assert f"/tests/scale/{test}" in plan_path.read_text()
    assert "python3 -m pytest" in (test_dir / "main.fmf").read_text()


def test_scale_workloads_inherit_common_configuration(tree):
    parent = content(tree, "plans/ovn-multihost/ovn-scale-testing/main.fmf")
    for setting in (
        "OTT_SCALE_TIMEOUT:",
        "OTT_SCALE_IPV4:",
        "OTT_SCALE_IPV6:",
        "OTT_SCALE_MTU:",
    ):
        assert setting in parent
    assert parent.count("role: compute") == 2
    assert "Install scale workload dependencies" in parent
