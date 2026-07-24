import shlex

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


def prepare_phase(tree, path, name=None, playbook=None):
    metadata = yaml.safe_load(content(tree, path)) or {}
    phases = []
    for key in ("prepare", "prepare+", "prepare+<"):
        value = metadata.get(key, [])
        phases.extend(value if isinstance(value, list) else [value])
    if name is None and playbook is None:
        assert len(phases) == 1
        return phases[0]
    return next(
        phase
        for phase in phases
        if (name is None or phase.get("name") == name)
        and (playbook is None or phase.get("playbook") == playbook)
    )


def extra_variables(phase):
    arguments = shlex.split(phase.get("extra-args", ""))
    return {
        assignment.split("=", 1)[0]: assignment.split("=", 1)[1]
        for option, assignment in zip(arguments, arguments[1:])
        if option == "-e" and "=" in assignment
    }


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


def test_plan_role_configuration_is_top_down(tree):
    for path, default in (
        ("plans/ovn-ci/main.fmf", "git"),
        ("plans/ovn-multihost/main.fmf", "artifact"),
    ):
        text = content(tree, path)
        assert f"OTT_INSTALL_METHOD: {default}" in text
        assert "-e ovn_install_method=$OTT_INSTALL_METHOD" in text

    plans = tree / "plans"
    for path in plans.rglob("*.fmf"):
        if path.is_relative_to(plans / "self"):
            continue
        metadata = yaml.safe_load(path.read_text()) or {}
        for key in ("prepare", "prepare+", "prepare+<"):
            phases = metadata.get(key, [])
            for phase in phases if isinstance(phases, list) else [phases]:
                arguments = shlex.split(phase.get("extra-args", ""))
                for option, assignment in zip(arguments, arguments[1:]):
                    if option == "-e" and "=" in assignment:
                        assert "$OTT_" in assignment, (path, assignment)


@pytest.mark.parametrize(
    ("path", "phase"),
    [
        ("plans/ovn-ci/main.fmf", None),
        ("plans/ovn-multihost/main.fmf", "Set up OVN topology"),
    ],
)
def test_install_configuration_is_complete(tree, path, phase):
    variables = extra_variables(prepare_phase(tree, path, phase))
    expected = {
        "ovn_install_method": "$OTT_INSTALL_METHOD",
        "ovn_install_cc": "$OTT_CC",
        "ovn_install_werror": "$OTT_WERROR",
        "ovn_install_dpdk_enabled": "$OTT_DPDK",
        "ovn_install_configure_flags": "$OTT_CONFIGURE_FLAGS",
        "ovn_install_git_repo": "$OTT_GIT_REPO",
        "ovn_install_git_version": "$OTT_GIT_VERSION",
        "ovn_install_source_dir": "$OTT_SOURCE_DIR",
        "ovn_install_make_flags": "$OTT_MAKE_FLAGS",
        "ovn_install_dpdk_dir": "$OTT_DPDK_DIR",
        "ovn_install_dpdk_version": "$OTT_DPDK_VERSION",
        "ovn_install_dpdk_checksum": "$OTT_DPDK_CHECKSUM",
        "ovn_install_dpdk_drivers": "$OTT_DPDK_DRIVERS",
        "ovn_install_dpdk_source_dir": "$OTT_DPDK_SOURCE_DIR",
        "ovn_install_distro_version": "$OTT_DISTRO_VERSION",
        "ovn_install_package_dir": "$OTT_PACKAGE_DIR",
        "ovn_install_package_files": "$OTT_PACKAGE_FILES",
        "ovn_artifact_name": "$OTT_ARTIFACT_NAME",
        "ovn_artifact_cache_dir": "$OTT_ARTIFACT_CACHE_DIR",
        "ovn_artifact_expected_revision": "$OTT_ARTIFACT_EXPECTED_REVISION",
    }
    assert variables.items() >= expected.items()


def test_multihost_parent_propagates_configuration(tree):
    path = "plans/ovn-multihost/main.fmf"
    expected = (
        "playbook: playbooks/ovn-build-artifact.yml",
        "playbook: playbooks/multihost-driver.yml",
        "playbook: playbooks/multihost-driver-authorize.yml",
        "OTT_INSTALL_METHOD: artifact",
        '-e \'ovn_artifact_enabled={{ "$OTT_INSTALL_METHOD" == "artifact" }}\'',
        "-e ovn_install_method=$OTT_INSTALL_METHOD",
        "-e ovn_artifact_build=$OTT_ARTIFACT_BUILD",
        "-e ovn_artifact_expected_revision=$OTT_ARTIFACT_EXPECTED_REVISION",
        "-e ovn_install_git_repo=$OTT_GIT_REPO",
        "-e ovn_install_git_version=$OTT_GIT_VERSION",
        "-e 'ovn_install_source_dir=$OTT_SOURCE_DIR'",
        "-e 'ovn_install_package_dir=$OTT_PACKAGE_DIR'",
        "-e 'ovn_install_package_files=$OTT_PACKAGE_FILES'",
        'OTT_SSL_ENABLED: "false"',
        'OTT_TEST_DEBUG: "false"',
        "playbook: playbooks/ovn-test-pki-create.yml",
        "playbook: playbooks/ovn-test-pki-install.yml",
        "-e ovn_test_pki_enabled=$OTT_SSL_ENABLED",
        "-e 'ovn_test_pki_remote_dir=$OTT_PKI_REMOTE_DIR'",
        "-e ovn_multihost_ssl_enabled=$OTT_SSL_ENABLED",
        "-e 'ovn_multihost_pki_dir=$OTT_PKI_REMOTE_DIR'",
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
    assert_contains(tree, "playbooks/multihost.yml", "ovn_multihost_pki_dir")
    assert_contains(tree, "roles/ovn_central/tasks/main.yml", "del-ssl")
    assert_contains(tree, "roles/ovs_setup/tasks/configure.yml", "del-ssl")
    assert_contains(
        tree,
        "plans/self/multihost/minimal.fmf",
        'OTT_SSL_ENABLED: "true"',
    )


def test_multihost_runtime_configuration_is_complete(tree):
    path = "plans/ovn-multihost/main.fmf"
    driver = extra_variables(
        prepare_phase(tree, path, "Set up cross-guest test driver")
    )
    authorize = extra_variables(
        prepare_phase(tree, path, "Authorize cross-guest test driver")
    )
    topology = extra_variables(prepare_phase(tree, path, "Set up OVN topology"))

    assert driver["multihost_driver_user"] == "$OTT_DRIVER_USER"
    assert driver["multihost_driver_runtime_dir"] == "$OTT_DRIVER_RUNTIME_DIR"
    assert "$OTT_DRIVER_KEY_PATH" in driver["multihost_driver_key_path"]
    assert "$OTT_DRIVER_RUNTIME_DIR" in driver["multihost_driver_key_path"]
    assert authorize == {"multihost_driver_user": "$OTT_DRIVER_USER"}
    assert (
        topology.items()
        >= {
            "ovn_multihost_sb_port": "$OTT_SB_PORT",
            "ovn_multihost_sb_wait_timeout": "$OTT_SB_WAIT_TIMEOUT",
            "ovn_gateway_chassis_name": "$OTT_GATEWAY_CHASSIS_NAME",
            "ovn_gateway_bridges": "$OTT_GATEWAY_BRIDGES",
            "ovn_gateway_bridge_mappings": "$OTT_GATEWAY_BRIDGE_MAPPINGS",
            "ovn_gateway_cms_options": "$OTT_GATEWAY_CMS_OPTIONS",
        }.items()
    )

    playbook = content(tree, "playbooks/multihost.yml")
    assert "ovn_multihost_sb_wait_timeout | default(2700)" in playbook
    assert "ovn_gateway_chassis_name | default(inventory_hostname, true)" in playbook
    assert "ovn_gateway_bridges | from_yaml" in playbook
    assert "ovn_gateway_cms_options | from_yaml" in playbook


def test_package_file_configuration_accepts_cli_list(tree):
    assert_contains(
        tree,
        "roles/ovn_install/tasks/package.yml",
        'ovn_install_package_files: "{{ (ovn_install_package_files | from_yaml) or [] }}"',
    )


def test_dpdk_plan_configuration_is_complete(tree):
    path = "plans/ovn-ci/system-dpdk-gcc.fmf"
    build = extra_variables(
        prepare_phase(tree, path, playbook="playbooks/dpdk-build.yml")
    )
    hugepages = extra_variables(
        prepare_phase(tree, path, playbook="playbooks/dpdk-hugepages.yml")
    )
    assert (
        build.items()
        >= {
            "dpdk_build_install_dir": "$OTT_DPDK_DIR",
            "dpdk_build_version": "$OTT_DPDK_VERSION",
            "dpdk_build_checksum": "$OTT_DPDK_CHECKSUM",
            "dpdk_build_drivers": "$OTT_DPDK_DRIVERS",
            "dpdk_build_source_dir": "$OTT_DPDK_SOURCE_DIR",
        }.items()
    )
    assert hugepages["dpdk_hugepages_count"] == "$OTT_DPDK_HUGEPAGES"
    assert_contains(
        tree,
        "roles/ovn_artifact/tasks/build.yml",
        'dpdk_build_source_dir: "{{ ovn_install_dpdk_source_dir',
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
    assert "duration: $OTT_SCALE_DURATION" in plan_path.read_text()
    assert "python3 -m pytest" in (test_dir / "main.fmf").read_text()
    assert "duration:" not in (test_dir / "main.fmf").read_text()


def test_scale_workloads_inherit_common_configuration(tree):
    parent = content(tree, "plans/ovn-multihost/ovn-scale-testing/main.fmf")
    for setting in (
        "OTT_SCALE_DURATION:",
        "OTT_SCALE_TIMEOUT:",
        "OTT_SCALE_IPV4:",
        "OTT_SCALE_IPV6:",
        "OTT_SCALE_MTU:",
    ):
        assert setting in parent
    assert parent.count("role: compute") == 2
    assert "Install scale workload dependencies" in parent
