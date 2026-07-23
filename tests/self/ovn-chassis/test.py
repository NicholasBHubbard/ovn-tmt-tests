import os

import pytest

from ovn_test.command import Runner
from ovn_test.ovsdb import Ovsdb
from ovn_test.system import processes


EXTERNAL_IDS = (
    "ovn-remote",
    "ovn-encap-type",
    "ovn-encap-ip",
    "ovn-cms-options",
    "ovn-bridge-mappings",
)


@pytest.fixture
def runner():
    return Runner()


@pytest.fixture
def ovs(runner):
    return Ovsdb(runner, "ovs-vsctl")


@pytest.fixture
def sb(runner):
    return Ovsdb(runner, "ovn-sbctl")


def external_ids(ovs):
    return ovs.value("Open_vSwitch", "external_ids")


def container_exists(runner, name):
    return runner.succeeds("podman", "container", "exists", name)


def container_started(runner, name):
    return runner.output(
        "podman",
        "inspect",
        "--format",
        "{{.State.StartedAt}}",
        name,
    )


class TestPreconditions:
    def test_controller_is_absent(self, runner):
        assert processes(runner, "ovn-controller") == []

    @pytest.mark.parametrize("bridge", ("br-int", "br-ex"))
    def test_bridge_is_absent(self, runner, bridge):
        assert not runner.succeeds("ovs-vsctl", "br-exists", bridge)

    @pytest.mark.parametrize("key", EXTERNAL_IDS)
    def test_external_id_is_absent(self, runner, key):
        assert not runner.succeeds(
            "ovs-vsctl",
            "get",
            "open",
            ".",
            f"external-ids:{key}",
        )


class TestInitial:
    def test_gateway_configuration(self, runner, ovs):
        assert runner.succeeds("ovs-vsctl", "br-exists", "br-ex")
        ids = external_ids(ovs)
        assert ids["ovn-cms-options"] == "enable-chassis-as-gw,prefer-chassis-as-gw"
        assert ids["ovn-bridge-mappings"] == "public:br-ex"


class TestReconfigured:
    def test_gateway_configuration(self, ovs):
        ids = external_ids(ovs)
        assert ids["ovn-cms-options"] == "enable-chassis-as-gw"
        assert ids["ovn-bridge-mappings"] == "provider:br-ex"


class TestInvalid:
    @pytest.mark.parametrize(
        ("case", "message"),
        [
            (
                "duplicate_names",
                "ovn_chassis_instances contains duplicate names.",
            ),
            (
                "duplicate_containers",
                "Podman chassis container names must be unique.",
            ),
            (
                "multiple_system",
                "Only one system chassis can use the host OVS database.",
            ),
            (
                "invalid_runtime",
                "Each chassis needs a valid unique name, runtime and state.",
            ),
        ],
    )
    def test_configuration_is_rejected(self, runner, tree, case, message):
        result = runner.run(
            "ansible-playbook",
            "-i",
            "localhost,",
            "-c",
            "local",
            tree / "tests/self/ovn-chassis/invalid-config.yml",
            "-e",
            f"ovn_chassis_invalid_case={case}",
            cwd=tree,
            check=False,
        )
        assert result.returncode
        assert message in result.stdout + result.stderr


class TestMulti:
    @pytest.mark.parametrize("chassis", ("scale-a", "scale-b"))
    def test_chassis_exists(self, runner, sb, chassis):
        assert container_exists(runner, f"ovn-chassis-{chassis}")
        assert sb.exists("Chassis", f"name={chassis}")

    def test_per_instance_images(self, runner):
        default = runner.output(
            "podman",
            "image",
            "inspect",
            "--format",
            "{{.Id}}",
            "localhost/ovn-chassis-selftest",
        )
        alternate = runner.output(
            "podman",
            "image",
            "inspect",
            "--format",
            "{{.Id}}",
            "localhost/ovn-chassis-selftest-alternate",
        )
        scale_a = runner.output(
            "podman",
            "inspect",
            "--format",
            "{{.Image}}",
            "ovn-chassis-scale-a",
        )
        scale_b = runner.output(
            "podman",
            "inspect",
            "--format",
            "{{.Image}}",
            "ovn-chassis-scale-b",
        )
        assert scale_a == default
        assert scale_b == alternate
        assert scale_a != scale_b
        assert not runner.succeeds(
            "podman",
            "exec",
            "ovn-chassis-scale-a",
            "test",
            "-f",
            "/ovn-chassis-image-alternate",
        )
        runner.run(
            "podman",
            "exec",
            "ovn-chassis-scale-b",
            "test",
            "-f",
            "/ovn-chassis-image-alternate",
        )

    def test_packet_connectivity(self, runner):
        runner.wait(
            "podman",
            "exec",
            "ovn-chassis-scale-a",
            "ping",
            "-c",
            "1",
            "-W",
            "1",
            "192.0.2.11",
            attempts=30,
        )


class TestMultiReconfigured:
    def test_removed_chassis_is_absent(self, runner, sb):
        assert not container_exists(runner, "ovn-chassis-scale-a")
        assert not sb.exists("Chassis", "name=scale-a")

    def test_retained_chassis_is_reconfigured(self, runner):
        assert container_exists(runner, "ovn-chassis-scale-b")
        assert (
            runner.output(
                "podman",
                "exec",
                "ovn-chassis-scale-b",
                "ovs-vsctl",
                "get",
                "Open_vSwitch",
                ".",
                "external_ids:ovn-bridge-mappings",
            ).strip('"')
            == "provider:br-ex"
        )
        assert (
            runner.output(
                "podman",
                "exec",
                "ovn-chassis-scale-b",
                "ovs-vsctl",
                "get",
                "Open_vSwitch",
                ".",
                "external_ids:ovn-cms-options",
            ).strip('"')
            == "enable-chassis-as-gw"
        )
        runner.run(
            "podman",
            "exec",
            "ovn-chassis-scale-b",
            "ovs-vsctl",
            "br-exists",
            "br-ex",
        )

    def test_identical_reapplication_does_not_restart(self, runner, snapshots):
        path = snapshots.path("ovn-chassis-started")
        if path.exists():
            assert container_started(runner, "ovn-chassis-scale-b") == snapshots.load(
                "ovn-chassis-started"
            )


class TestRecordContainer:
    def test_start_time_is_recorded(self, runner, snapshots):
        snapshots.save(
            "ovn-chassis-started",
            container_started(runner, "ovn-chassis-scale-b"),
        )


class TestImageRefresh:
    def test_updated_image_recreates_chassis(self, runner, snapshots, sb):
        assert container_started(runner, "ovn-chassis-scale-b") != snapshots.load(
            "ovn-chassis-started"
        )
        runner.run(
            "podman",
            "exec",
            "ovn-chassis-scale-b",
            "test",
            "-f",
            "/ovn-chassis-image-updated",
        )
        assert sb.exists("Chassis", "name=scale-b")


class TestResult:
    def test_tls_chassis(self, runner, sb):
        if os.environ.get("OTT_CHASSIS_TEST_MODE", "system") != "tls":
            pytest.skip("system chassis plan")
        for chassis in ("scale-a", "scale-b"):
            assert container_exists(runner, f"ovn-chassis-{chassis}")
            assert sb.exists("Chassis", f"name={chassis}")

    def test_system_chassis(self, runner, ovs, sb):
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
            "system-id",
        ):
            assert key in ids
        assert "ovn-cms-options" not in ids
        assert "ovn-bridge-mappings" not in ids
        assert sb.exists("Chassis", f"name={ids['system-id']}")
