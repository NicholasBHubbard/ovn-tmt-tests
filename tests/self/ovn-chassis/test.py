import os
from pathlib import Path
from typing import Any

import pytest
from ovn_test.command import Runner
from ovn_test.ovsdb import Ovsdb
from ovn_test.system import processes

EXTERNAL_IDS = (
    "ovn-remote",
    "ovn-encap-type",
    "ovn-encap-ip",
    "ovn-bridge",
    "ovn-cms-options",
    "ovn-monitor-all",
    "ovn-bridge-mappings",
)


@pytest.fixture
def runner() -> Runner:
    return Runner()


@pytest.fixture
def ovs(runner: Runner) -> Ovsdb:
    return Ovsdb(runner, "ovs-vsctl")


@pytest.fixture
def sb(runner: Runner) -> Ovsdb:
    return Ovsdb(runner, "ovn-sbctl")


def external_ids(ovs: Ovsdb) -> Any:
    return ovs.value("Open_vSwitch", "external_ids")


class TestPreconditions:
    def test_controller_is_absent(self, runner: Runner) -> None:
        assert processes(runner, "ovn-controller") == []

    @pytest.mark.parametrize(
        "bridge", ("br-int", "br-ex", "self-br-int", "self-br-new")
    )
    def test_bridge_is_absent(self, runner: Runner, bridge: str) -> None:
        assert not runner.succeeds("ovs-vsctl", "br-exists", bridge)

    @pytest.mark.parametrize("key", EXTERNAL_IDS)
    def test_external_id_is_absent(self, runner: Runner, key: str) -> None:
        assert not runner.succeeds(
            "ovs-vsctl",
            "get",
            "open",
            ".",
            f"external-ids:{key}",
        )


class TestInitial:
    def test_gateway_configuration(self, runner: Runner, ovs: Ovsdb) -> None:
        assert runner.succeeds("ovs-vsctl", "br-exists", "self-br-int")
        assert runner.succeeds("ovs-vsctl", "br-exists", "br-ex")
        ids = external_ids(ovs)
        assert ids["ovn-bridge"] == "self-br-int"
        assert ids["ovn-cms-options"] == "enable-chassis-as-gw,prefer-chassis-as-gw"
        assert ids["ovn-monitor-all"] == "true"
        assert ids["ovn-bridge-mappings"] == "public:br-ex"


class TestReconfigured:
    def test_gateway_configuration(self, ovs: Ovsdb) -> None:
        ids = external_ids(ovs)
        assert ids["ovn-bridge"] == "self-br-new"
        assert ids["ovn-cms-options"] == "enable-chassis-as-gw"
        assert "ovn-monitor-all" not in ids
        assert ids["ovn-bridge-mappings"] == "provider:br-ex"


class TestInvalid:
    @pytest.mark.parametrize(
        ("case", "message"),
        (
            (
                "invalid_name",
                "OVN chassis configuration is invalid.",
            ),
            (
                "empty_integration_bridge",
                "OVN chassis configuration is invalid.",
            ),
            (
                "invalid_ready_timeout",
                "OVN chassis configuration is invalid.",
            ),
            (
                "invalid_ready_delay",
                "OVN chassis configuration is invalid.",
            ),
        ),
    )
    def test_configuration_is_rejected(
        self, runner: Runner, tree: Path, case: Any, message: str
    ) -> None:
        result = runner.run(
            "ansible-playbook",
            "-i",
            "localhost,",
            "-c",
            "local",
            tree / "tests/self/ovn-chassis/invalid-configuration.yml",
            "-e",
            f"ovn_chassis_invalid_case={case}",
            cwd=tree,
            check=False,
        )
        assert result.returncode
        assert message in result.stdout + result.stderr


class TestResult:
    def test_tls_chassis(self, runner: Runner, sb: Ovsdb) -> None:
        if os.environ.get("OTT_CHASSIS_TEST_MODE", "system") != "tls":
            pytest.skip("system chassis plan")
        assert processes(runner, "ovn-controller")
        assert (
            runner.output(
                "ovn-appctl",
                "-t",
                "ovn-controller",
                "connection-status",
            )
            == "connected"
        )
        assert runner.output("ovs-vsctl", "get", "Open_vSwitch", ".", "ssl") != "[]"
        assert sb.exists("Chassis", "name=tls-chassis")

    def test_system_chassis(self, runner: Runner, ovs: Ovsdb, sb: Ovsdb) -> None:
        if os.environ.get("OTT_CHASSIS_TEST_MODE", "system") == "tls":
            pytest.skip("TLS chassis plan")
        assert processes(runner, "ovn-controller")
        for bridge in ("br-int", "br-ex"):
            assert runner.succeeds("ovs-vsctl", "br-exists", bridge)
        ids = external_ids(ovs)
        for key in (
            "ovn-remote",
            "ovn-encap-type",
            "ovn-encap-ip",
            "ovn-bridge",
            "system-id",
        ):
            assert key in ids
        assert "ovn-cms-options" not in ids
        assert "ovn-bridge-mappings" not in ids
        assert ids["ovn-bridge"] == "br-int"
        assert sb.exists("Chassis", f"name={ids['system-id']}")
