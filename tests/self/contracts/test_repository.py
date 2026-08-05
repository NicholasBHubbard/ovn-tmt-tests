import shlex
import subprocess
from pathlib import Path
from typing import Any, Optional, Union

import pytest
import yaml
from ovn_test.command import Runner
from ovn_test.files import find_text

INHERITED_SELF_PLANS = (
    "brew-packages",
    "ci",
    "dpdk-build",
    "kube-burner",
    "multihost",
    "ovn-central",
    "ovn-central-ssl",
    "ovn-clustered",
    "ovn-endpoints",
    "ovn-chassis",
    "ovn-install",
    "ovn-sb-convergence",
    "ovn-scale-topology",
    "ovn-system-test-deps",
    "ovn-topology",
    "ovn-unit-test-deps",
    "ovs-endpoints",
    "ovs-external-ids",
    "ovs-setup",
)


def content(tree: Path, path: Union[str, Path]) -> str:
    return (tree / path).read_text()


def assert_contains(tree: Path, path: Union[str, Path], expected: Any) -> None:
    assert expected in content(tree, path), path


def plan_metadata(
    tree: Path, path: Union[str, Path], node: Optional[str] = None
) -> dict[str, Any]:
    metadata = yaml.safe_load(content(tree, path)) or {}
    return metadata if node is None else metadata[f"/{node}"]


def prepare_phase(
    tree: Path,
    path: Union[str, Path],
    name: Optional[str] = None,
    playbook: Optional[str] = None,
    node: Optional[str] = None,
) -> dict[str, Any]:
    metadata = plan_metadata(tree, path, node)
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


def extra_variables(phase: dict[str, Any]) -> dict[str, str]:
    arguments = shlex.split(phase.get("extra-args", ""))
    return {
        assignment.split("=", 1)[0]: assignment.split("=", 1)[1]
        for option, assignment in zip(arguments, arguments[1:])
        if option == "-e" and "=" in assignment
    }


def run_naming(tree: Path, root: Path) -> subprocess.CompletedProcess[str]:
    return Runner().run(
        "python3",
        tree / "tools/check-naming.py",
        root,
        check=False,
    )


class TestPreconditions:
    def test_self_test_directory_exists(self, tree: Path) -> None:
        assert (tree / "tests/self").is_dir()


class TestNaming:
    def test_valid_names(self, tree: Path, tmp_path: Path) -> None:
        defaults = tmp_path / "roles/example/defaults"
        plans = tmp_path / "plans"
        defaults.mkdir(parents=True)
        plans.mkdir()
        (defaults / "main.yaml").write_text("example: []\n")
        (plans / "main.fmf").write_text("environment:\n  OTT_EXAMPLE: value\n")

        assert run_naming(tree, tmp_path).returncode == 0

    def test_invalid_role_variable(self, tree: Path, tmp_path: Path) -> None:
        defaults = tmp_path / "roles/example/defaults"
        defaults.mkdir(parents=True)
        (tmp_path / "plans").mkdir()
        (defaults / "main.yaml").write_text("wrong_name: true\n")

        assert run_naming(tree, tmp_path).returncode != 0

    def test_invalid_environment_variable(self, tree: Path, tmp_path: Path) -> None:
        defaults = tmp_path / "roles/example/defaults"
        plans = tmp_path / "plans"
        defaults.mkdir(parents=True)
        plans.mkdir()
        (defaults / "main.yaml").write_text("example: []\n")
        (plans / "main.fmf").write_text("environment:\n  WRONG_NAME: value\n")

        assert run_naming(tree, tmp_path).returncode != 0

    def test_missing_root(self, tree: Path, tmp_path: Path) -> None:
        assert run_naming(tree, tmp_path / "missing").returncode != 0

    def test_repository_names(self, tree: Path) -> None:
        assert run_naming(tree, tree).returncode == 0


def test_every_self_test_is_referenced_by_a_plan(tree: Path) -> None:
    plans = tree / "plans/self"
    for test_dir in (tree / "tests/self").iterdir():
        if not test_dir.is_dir() or test_dir.name.startswith((".", "__")):
            continue
        assert (test_dir / "main.fmf").is_file()
        assert list(test_dir.glob("test*.py"))
        assert find_text(plans, f"/tests/self/{test_dir.name}")


def test_role_readmes_follow_common_structure(tree: Path) -> None:
    readmes = sorted((tree / "roles").glob("*/README.md"))
    assert readmes
    for readme in readmes:
        text = readme.read_text()
        assert text.startswith(f"# {readme.parent.name}\n")
        assert "playbooks/" not in text
        sections = [
            text.index(f"## {name}")
            for name in (
                "Purpose",
                "Configuration",
                "Usage",
            )
        ]
        assert sections == sorted(sections)


def test_pytest_prepare_phases_run_after_test_dependencies(tree: Path) -> None:
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
def test_self_test_children_inherit_common_steps(tree: Path, plan_dir: Path) -> None:
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


def test_disabled_self_test_parents_use_main_metadata(tree: Path) -> None:
    for path in (tree / "plans/self").rglob("base.fmf"):
        assert "\nenabled: false\n" not in f"\n{path.read_text()}\n"


def test_sb_convergence_has_a_focused_self_test(tree: Path) -> None:
    family = "ovn-sb-convergence"
    role_reference = "role: ovn_sb_convergence"
    assert find_text(tree / "tests/self" / family, role_reference)
    assert find_text(tree / "plans/self" / family, f"/tests/self/{family}")

    generic = tree / "tests/self/ovn-topology"
    assert not find_text(generic, role_reference)


def test_ovn_ci_children_inherit_execution(tree: Path) -> None:
    directory = tree / "plans/ovn-ci"
    for plan in directory.glob("*.fmf"):
        if plan.name != "main.fmf":
            assert "\nexecute:" not in f"\n{plan.read_text()}"


def test_plan_role_configuration_is_top_down(tree: Path) -> None:
    for path, default in (
        ("plans/ovn-ci/main.fmf", "git"),
        ("plans/main.fmf", "artifact"),
    ):
        text = content(tree, path)
        assert f"OTT_INSTALL_METHOD: {default}" in text
        assert "-e ovn_install_method=$OTT_INSTALL_METHOD" in text

    plans = tree / "plans"
    for path in plans.rglob("*.fmf"):
        if path.is_relative_to(plans / "self"):
            continue
        metadata = yaml.safe_load(path.read_text()) or {}
        nodes = [metadata]
        nodes.extend(
            value
            for key, value in metadata.items()
            if key.startswith("/") and key != "/" and isinstance(value, dict)
        )
        for node in nodes:
            for key in ("prepare", "prepare+", "prepare+<"):
                phases = node.get(key, [])
                for phase in phases if isinstance(phases, list) else [phases]:
                    arguments = shlex.split(phase.get("extra-args", ""))
                    for option, assignment in zip(arguments, arguments[1:]):
                        if option == "-e" and "=" in assignment:
                            assert "$OTT_" in assignment, (path, assignment)


@pytest.mark.parametrize(
    ("path", "phase", "node"),
    (
        ("plans/ovn-ci/main.fmf", None, None),
        ("plans/main.fmf", "Set up OVN topology", "ovn-fake-multinode"),
    ),
)
def test_install_configuration_is_complete(
    tree: Path, path: Path, phase: Optional[str], node: Optional[str]
) -> None:
    variables = extra_variables(prepare_phase(tree, path, phase, node=node))
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


def test_multihost_parent_propagates_configuration(tree: Path) -> None:
    path = "plans/main.fmf"
    expected = (
        "playbook: playbooks/ovn-build-artifact.yml",
        "playbook: playbooks/multihost-driver.yml",
        "playbook: playbooks/multihost-driver-authorize.yml",
        "playbook: playbooks/run-diagnostics-start.yml",
        "playbook: playbooks/run-diagnostics-collect.yml",
        "OTT_INSTALL_METHOD: artifact",
        'OTT_DIAGNOSTICS: "true"',
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
        "-e ovn_multihost_clustered=$OTT_CLUSTERED",
        "-e ovn_multihost_monitor_all=$OTT_MONITOR_ALL",
        "-e ovn_multihost_nb_port=$OTT_NB_PORT",
        "-e ovn_multihost_nb_raft_port=$OTT_NB_RAFT_PORT",
        "-e ovn_multihost_sb_raft_port=$OTT_SB_RAFT_PORT",
        "-e 'ovn_multihost_central_listen_address=$OTT_CENTRAL_LISTEN_ADDRESS'",
        "-e ovn_multihost_central_log_level=$OTT_CENTRAL_LOG_LEVEL",
        "-e ovn_multihost_reconcile_cluster_members=$OTT_RECONCILE_CLUSTER_MEMBERS",
    )
    for value in expected:
        assert_contains(tree, path, value)
    assert_contains(tree, path, "enabled: false")


def test_multihost_diagnostics_are_general_and_top_down(tree: Path) -> None:
    path = "plans/main.fmf"
    metadata = plan_metadata(tree, path, "ovn-fake-multinode")
    start = prepare_phase(
        tree, path, "Start guest diagnostics", node="ovn-fake-multinode"
    )
    collect = metadata["finish"][0]

    assert start["playbook"] == "playbooks/run-diagnostics-start.yml"
    assert collect["playbook"] == "playbooks/run-diagnostics-collect.yml"
    assert extra_variables(start) == {
        "run_diagnostics_enabled": "$OTT_DIAGNOSTICS",
        "run_diagnostics_runtime_dir": "$OTT_DIAGNOSTICS_RUNTIME_DIR",
    }
    assert extra_variables(collect) == {
        "run_diagnostics_enabled": "$OTT_DIAGNOSTICS",
        "run_diagnostics_runtime_dir": "$OTT_DIAGNOSTICS_RUNTIME_DIR",
        "run_diagnostics_journal_lines": "$OTT_DIAGNOSTICS_JOURNAL_LINES",
        "run_diagnostics_log_bytes": "$OTT_DIAGNOSTICS_LOG_BYTES",
        "run_diagnostics_output_dir": "$TMT_PLAN_DATA/diagnostics",
    }


def test_multihost_tls_contract(tree: Path) -> None:
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
    assert_contains(tree, "roles/ovn_central/tasks/listeners.yml", "del-ssl")
    assert_contains(tree, "roles/ovs_setup/tasks/configure.yml", "del-ssl")
    assert_contains(
        tree,
        "plans/self/multihost/minimal.fmf",
        'OTT_SSL_ENABLED: "true"',
    )


def test_multihost_runtime_configuration_is_complete(tree: Path) -> None:
    path = "plans/main.fmf"
    driver = extra_variables(
        prepare_phase(
            tree, path, "Set up cross-guest test driver", node="ovn-fake-multinode"
        )
    )
    authorize = extra_variables(
        prepare_phase(
            tree,
            path,
            "Authorize cross-guest test driver",
            node="ovn-fake-multinode",
        )
    )
    topology = extra_variables(
        prepare_phase(tree, path, "Set up OVN topology", node="ovn-fake-multinode")
    )

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
            "ovn_multihost_clustered": "$OTT_CLUSTERED",
            "ovn_multihost_monitor_all": "$OTT_MONITOR_ALL",
            "ovn_multihost_nb_port": "$OTT_NB_PORT",
            "ovn_multihost_nb_raft_port": "$OTT_NB_RAFT_PORT",
            "ovn_multihost_sb_raft_port": "$OTT_SB_RAFT_PORT",
            "ovn_multihost_central_listen_address": "$OTT_CENTRAL_LISTEN_ADDRESS",
            "ovn_multihost_central_log_level": "$OTT_CENTRAL_LOG_LEVEL",
            "ovn_multihost_reconcile_cluster_members": "$OTT_RECONCILE_CLUSTER_MEMBERS",
            "ovn_compute_physical_bridge": "$OTT_COMPUTE_PHYSICAL_BRIDGE",
            "ovn_compute_physical_network": "$OTT_COMPUTE_PHYSICAL_NETWORK",
            "ovn_gateway_chassis_name": "$OTT_GATEWAY_CHASSIS_NAME",
            "ovn_gateway_bridges": "$OTT_GATEWAY_BRIDGES",
            "ovn_gateway_bridge_mappings": "$OTT_GATEWAY_BRIDGE_MAPPINGS",
            "ovn_gateway_cms_options": "$OTT_GATEWAY_CMS_OPTIONS",
        }.items()
    )

    playbook = content(tree, "playbooks/multihost.yml")
    assert "ovn_multihost_sb_wait_timeout | default(2700)" in playbook
    assert "ovn_gateway_chassis_name | default(inventory_hostname, true)" in playbook
    assert (
        "ovn_compute_physical_network ~ ':' ~ ovn_compute_physical_bridge" in playbook
    )
    assert "ovn_gateway_bridges | from_yaml" in playbook
    assert "ovn_gateway_cms_options | from_yaml" in playbook


def test_ovn_chassis_uses_shared_install_paths(tree: Path) -> None:
    tasks = content(tree, "roles/ovn_chassis/tasks/main.yml")
    defaults = content(tree, "roles/ovn_chassis/defaults/main.yml")
    configure = content(tree, "roles/ovn_chassis/tasks/configure.yml")
    assert "ovn_install_ovn_ctl_path" in tasks
    assert "ansible.builtin.find" not in tasks
    assert "ovn_chassis_ready_timeout" in defaults
    assert "ovn_chassis_ready_delay" in defaults
    assert "external-ids:ovn-bridge={{ ovn_chassis_integration_bridge }}" in configure


def test_package_file_configuration_accepts_cli_list(tree: Path) -> None:
    assert_contains(
        tree,
        "roles/ovn_install/tasks/package.yml",
        'ovn_install_package_files: "{{ (ovn_install_package_files | from_yaml) or [] }}"',
    )


def test_dpdk_plan_configuration_is_complete(tree: Path) -> None:
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


def test_make_check_configuration_is_top_down(tree: Path) -> None:
    plan = plan_metadata(tree, "plans/ovn-ci/main.fmf")

    assert plan["environment"]["OTT_MAKE_CHECK_TESTSUITEFLAGS"] == ""
    assert plan["environment"]["OTT_MAKE_JOBS"] == ""
    assert_contains(
        tree,
        "tests/ovn-ci/make-check/test.py",
        'os.environ.get("OTT_MAKE_CHECK_TESTSUITEFLAGS")',
    )
    assert_contains(tree, "tests/lib/ovn_test/pytest_build.py", '"OTT_MAKE_JOBS"')
    for path in ("tests/ovn-ci/make-check/test.py", "tests/ovn-ci/distcheck/test.py"):
        assert_contains(tree, path, "jobs=make_jobs")


def test_multihost_children_inherit_base(tree: Path) -> None:
    for family in ("ovn-fake-multinode", "ovn-scale-testing"):
        for plan in (tree / "plans" / family).rglob("*.fmf"):
            if plan.name == "main.fmf":
                continue
            assert "playbook: playbooks/multihost.yml" not in plan.read_text()
            assert "enabled: true" in plan.read_text()


def test_top_level_plan_inheritance_is_explicit(tree: Path) -> None:
    plans = tree / "plans"
    shared = {"ovn-fake-multinode", "ovn-scale-testing"}
    assert {path.name for path in plans.iterdir() if path.is_dir()} >= shared

    root = plan_metadata(tree, "plans/main.fmf")
    assert root["/"] == {"inherit": False}
    assert {key.removeprefix("/") for key in root if key != "/"} == shared

    fake = root["/ovn-fake-multinode"]
    scale = root["/ovn-scale-testing"]
    assert fake["environment"].items() <= scale["environment"].items()
    scale_prepare = [
        phase
        for phase in scale["prepare"]
        if phase["name"] != "Install scale workload dependencies"
    ]
    assert len(fake["prepare"]) == len(scale_prepare)
    assert all(
        fake_phase is scale_phase
        for fake_phase, scale_phase in zip(fake["prepare"], scale_prepare)
    )
    assert fake["execute"] is scale["execute"]
    assert fake["finish"] is scale["finish"]
    assert "<<: *multihost_plan" in content(tree, "plans/main.fmf")
    assert "<<: *multihost_environment" in content(tree, "plans/main.fmf")
    assert "discover" not in fake
    assert "discover" not in scale

    for family in (path for path in plans.iterdir() if path.is_dir()):
        parent = family / "main.fmf"
        if family.name in shared:
            assert not parent.exists()
            continue
        assert parent.is_file(), family
        metadata = yaml.safe_load(parent.read_text()) or {}
        assert metadata.get("/", {}).get("inherit") is False, family


def test_multihost_setup_is_test_scoped(tree: Path) -> None:
    plans = "\n".join(
        path.read_text() for path in (tree / "plans/ovn-fake-multinode").rglob("*.fmf")
    )
    for setup in (tree / "tests/ovn-fake-multinode").glob("*/setup.yml"):
        if setup.parent.name == "gateway-nat":
            continue
        test = setup.with_name("test.py")
        assert test.is_file()
        assert 'pytest.mark.usefixtures("setup_scenario")' in test.read_text()
        assert str(setup).removeprefix(f"{tree}/") not in plans


def test_artifact_role_contract(tree: Path) -> None:
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
    assert install.index("- name: Install OVN artifact archive tools") < install.index(
        "- name: Install OVN artifact\n"
    )
    assert (
        'distro_packages_names: "{{ ovn_artifact_archive_package_names }}"' in install
    )
    build = content(tree, "roles/ovn_artifact/tasks/build.yml")
    assert build.index("- name: Install OVN artifact archive tools") < build.index(
        "- name: Create OVN artifact\n"
    )
    validate = content(tree, "roles/ovn_artifact/tasks/validate.yml")
    assert "- name: Verify local OVN artifact checksum" in validate
    assert "ovn_artifact_identity:" in validate


@pytest.mark.parametrize(
    ("plan", "test", "settings"),
    (
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
                "OTT_SCALE_BASE_PODS_PER_WORKER:",
                "OTT_CLUSTERED:",
                "OTT_COMPUTE_PHYSICAL_BRIDGE:",
                "OTT_COMPUTE_PHYSICAL_NETWORK:",
                "OTT_MONITOR_ALL:",
                "OTT_SCALE_INITIAL_PODS:",
                "OTT_SCALE_PODS_PER_SERVICE:",
                "OTT_SCALE_LB_PROTOCOLS:",
                "OTT_SCALE_TOTAL_PODS:",
                "OTT_SCALE_WORKERS:",
            ),
        ),
        (
            "cluster-density.fmf",
            "cluster-density",
            (
                "OTT_SCALE_BASE_PODS_PER_WORKER:",
                "OTT_SCALE_BUILD_PODS_PER_NAMESPACE:",
                "OTT_CLUSTERED:",
                "OTT_COMPUTE_PHYSICAL_BRIDGE:",
                "OTT_COMPUTE_PHYSICAL_NETWORK:",
                "OTT_MONITOR_ALL:",
                "OTT_SCALE_INITIAL_NAMESPACES:",
                "OTT_SCALE_LB_PROTOCOLS:",
                "OTT_SCALE_TEST_PODS_PER_NAMESPACE:",
                "OTT_SCALE_TOTAL_NAMESPACES:",
                "OTT_SCALE_WORKERS:",
            ),
        ),
        (
            "np-multitenant.fmf",
            "np-multitenant",
            (
                "OTT_SCALE_BASE_PODS_PER_WORKER:",
                "OTT_CLUSTERED:",
                "OTT_COMPUTE_PHYSICAL_BRIDGE:",
                "OTT_COMPUTE_PHYSICAL_NETWORK:",
                "OTT_MONITOR_ALL:",
                "OTT_SCALE_EXTERNAL_IPV4_LARGE_START:",
                "OTT_SCALE_EXTERNAL_IPV4_SMALL_START:",
                "OTT_SCALE_EXTERNAL_IPV6_LARGE_START:",
                "OTT_SCALE_EXTERNAL_IPV6_SMALL_START:",
                "OTT_SCALE_EXTERNAL_LARGE_COUNT:",
                "OTT_SCALE_EXTERNAL_SMALL_COUNT:",
                "OTT_SCALE_NAMESPACES:",
                "OTT_SCALE_NAMESPACE_RANGES:",
                "OTT_SCALE_POLICY_ALLOW_PRIORITY:",
                "OTT_SCALE_POLICY_CONTROL_PRIORITY:",
                "OTT_SCALE_POLICY_DENY_PRIORITY:",
                "OTT_SCALE_WORKERS:",
            ),
        ),
        (
            "np-cross-namespace.fmf",
            "np-cross-namespace",
            (
                "OTT_SCALE_BASE_PODS_PER_WORKER:",
                "OTT_CLUSTERED:",
                "OTT_COMPUTE_PHYSICAL_BRIDGE:",
                "OTT_COMPUTE_PHYSICAL_NETWORK:",
                "OTT_MONITOR_ALL:",
                "OTT_SCALE_LB_PROTOCOLS:",
                "OTT_SCALE_NAMESPACES:",
                "OTT_SCALE_PODS_PER_NAMESPACE:",
                "OTT_SCALE_POLICY_ALLOW_PRIORITY:",
                "OTT_SCALE_POLICY_CONTROL_PRIORITY:",
                "OTT_SCALE_POLICY_DENY_PRIORITY:",
                "OTT_SCALE_WORKERS:",
            ),
        ),
        (
            "np-labels/main.fmf",
            "np-labels",
            (
                "OTT_SCALE_BASE_PODS_PER_WORKER:",
                "OTT_CLUSTERED:",
                "OTT_COMPUTE_PHYSICAL_BRIDGE:",
                "OTT_COMPUTE_PHYSICAL_NETWORK:",
                "OTT_MONITOR_ALL:",
                "OTT_SCALE_LABELS:",
                "OTT_SCALE_LB_PROTOCOLS:",
                "OTT_SCALE_NAMESPACES:",
                "OTT_SCALE_PODS_PER_NAMESPACE:",
                "OTT_SCALE_POLICY_ALLOW_PRIORITY:",
                "OTT_SCALE_POLICY_CONTROL_PRIORITY:",
                "OTT_SCALE_POLICY_DENY_PRIORITY:",
                "OTT_SCALE_WORKERS:",
            ),
        ),
        (
            "service-route.fmf",
            "service-route",
            (
                "OTT_SCALE_BASE_PODS_PER_WORKER:",
                "OTT_CLUSTERED:",
                "OTT_COMPUTE_PHYSICAL_BRIDGE:",
                "OTT_COMPUTE_PHYSICAL_NETWORK:",
                "OTT_MONITOR_ALL:",
                "OTT_SCALE_LB_PROTOCOLS:",
                "OTT_SCALE_SERVICE_BACKENDS:",
                "OTT_SCALE_SERVICE_LOAD_BALANCERS:",
                "OTT_SCALE_WORKERS:",
            ),
        ),
    ),
)
def test_scale_workload_contract(
    tree: Path, plan: Any, test: Any, settings: Any
) -> None:
    plan_path = tree / "plans/ovn-scale-testing" / plan
    test_dir = tree / "tests/ovn-scale-testing" / test
    assert plan_path.is_file()
    assert (test_dir / "main.fmf").is_file()
    assert (test_dir / "test.py").is_file()
    for setting in settings:
        assert setting in plan_path.read_text()
    assert f"/tests/ovn-scale-testing/{test}" in plan_path.read_text()
    assert "duration: $OTT_SCALE_DURATION" in plan_path.read_text()
    assert "python3 -m pytest" in (test_dir / "main.fmf").read_text()
    assert "duration:" not in (test_dir / "main.fmf").read_text()
    if test in {"density-heavy", "cluster-density", "np-multitenant"}:
        metadata = yaml.safe_load(plan_path.read_text())
        assert metadata["environment+"]["OTT_SCALE_IPV6"] == "false"
    if test in {
        "density-heavy",
        "cluster-density",
        "np-multitenant",
        "np-cross-namespace",
        "np-labels",
        "service-route",
    }:
        metadata = yaml.safe_load(plan_path.read_text())
        assert [guest["role"] for guest in metadata["provision+"]] == [
            "central-follower",
            "central-follower",
        ]


@pytest.mark.parametrize("mode", ("small", "large"))
def test_label_policy_plans_share_one_workload(tree: Path, mode: str) -> None:
    path = tree / "plans/ovn-scale-testing/np-labels" / f"{mode}.fmf"
    metadata = yaml.safe_load(path.read_text())

    assert metadata["enabled"] is True
    assert metadata["environment+"]["OTT_SCALE_LABEL_MODE"] == mode


def test_scale_workloads_inherit_common_configuration(tree: Path) -> None:
    parent = plan_metadata(tree, "plans/main.fmf", "ovn-scale-testing")
    for setting in (
        "OTT_SCALE_DURATION",
        "OTT_SCALE_TIMEOUT",
        "OTT_SCALE_IPV4",
        "OTT_SCALE_IPV6",
        "OTT_SCALE_MTU",
        "OTT_SCALE_SYNC_TIMEOUT",
    ):
        assert setting in parent["environment"]
    assert [guest["role"] for guest in parent["provision"]].count("compute") == 2
    assert "Install scale workload dependencies" in {
        phase["name"] for phase in parent["prepare"]
    }
