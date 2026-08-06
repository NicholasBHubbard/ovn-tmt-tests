import shlex
from pathlib import Path
from typing import Any, Optional

import pytest
import yaml

from ._metadata import (
    assert_contains,
    content,
    extra_variables,
    plan_metadata,
    prepare_phase,
)


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
    environment = plan_metadata(tree, path, node="ovn-fake-multinode")["environment"]
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
    assert environment["OTT_DRIVER_CONNECT_TIMEOUT"] == "30"
    assert environment["OTT_INTEGRATION_BRIDGE"] == "br-int"
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
            "ovn_multihost_integration_bridge": "$OTT_INTEGRATION_BRIDGE",
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
    assert_contains(tree, "tests/ovn-ci/conftest.py", '"OTT_MAKE_JOBS"')
    for path in ("tests/ovn-ci/make-check/test.py", "tests/ovn-ci/distcheck/test.py"):
        assert_contains(tree, path, "jobs=make_jobs")


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
                "OTT_SCALE_SERVICE_BACKEND_PORT:",
                "OTT_SCALE_SERVICE_VIP_IPV4_NETWORK:",
                "OTT_SCALE_SERVICE_VIP_IPV6_NETWORK:",
                "OTT_SCALE_SERVICE_VIP_PORT:",
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
    assert '"OTT_INTEGRATION_BRIDGE"' in (test_dir / "test.py").read_text()
    if test == "density-light":
        source = (test_dir / "test.py").read_text()
        assert "OTT_SCALE_ENDPOINT_IPV4_NETWORK" in source
        assert "OTT_SCALE_ENDPOINT_IPV6_NETWORK" in source
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
        "OTT_INTEGRATION_BRIDGE",
        "OTT_SCALE_DURATION",
        "OTT_SCALE_ENDPOINT_IPV4_NETWORK",
        "OTT_SCALE_ENDPOINT_IPV6_NETWORK",
        "OTT_SCALE_TIMEOUT",
        "OTT_SCALE_IPV4",
        "OTT_SCALE_IPV6",
        "OTT_SCALE_MTU",
        "OTT_SCALE_SYNC_TIMEOUT",
    ):
        assert setting in parent["environment"]
    assert parent["environment"]["OTT_INTEGRATION_BRIDGE"] == "br-int"
    assert [guest["role"] for guest in parent["provision"]].count("compute") == 2
    assert "Install scale workload dependencies" in {
        phase["name"] for phase in parent["prepare"]
    }
