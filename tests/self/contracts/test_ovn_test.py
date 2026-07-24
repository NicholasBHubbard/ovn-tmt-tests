import subprocess

import pytest
import yaml

from ovn_test.command import Runner
from ovn_test.config import read_bool, read_int, read_list
from ovn_test.topology import Topology
from ovn_test.workload import (
    Workload,
    validate_heavy,
    validate_light,
)


class FakeRunner:
    def __init__(self):
        self.calls = []
        self.batches = []
        self.fail = set()
        self.returncodes = {}
        self.waits = []

    def run(self, *command, guest=None, input=None, check=True):
        self.calls.append((guest, command, input))
        if command in self.fail:
            raise subprocess.CalledProcessError(1, command)
        stdout = ""
        if command[:3] == ("ovn-nbctl", "create", "Address_Set"):
            stdout = f"uuid-{len(self.calls)}\n"
        if "Logical_Switch_Port" in command:
            stdout = "logical-port-uuid\n"
        if "Port_Binding" in command:
            stdout = "chassis-uuid\n"
        return subprocess.CompletedProcess(
            command,
            self.returncodes.get(command, 0),
            stdout,
            "",
        )

    def output(self, *command, **options):
        return self.run(*command, **options).stdout.strip()

    def run_many(self, commands, guest=None):
        self.batches.append((guest, commands))
        return subprocess.CompletedProcess([], 0, "", "")

    def wait(self, *command, **options):
        self.waits.append((command, options))
        result = self.run(*command, check=False, guest=options.get("guest"))
        condition = options.get("until")
        if condition is not None and not condition(result):
            raise TimeoutError(command)
        return result


def topology_data():
    return {
        "guest": {"name": "central", "hostname": "192.0.2.1", "role": "central"},
        "guests": {
            "central": {
                "name": "central",
                "hostname": "192.0.2.1",
                "role": "central",
            },
            "compute-1": {
                "name": "compute-1",
                "hostname": "192.0.2.2",
                "role": "compute",
            },
            "compute-2": {
                "name": "compute-2",
                "hostname": "192.0.2.3",
                "role": "compute",
            },
        },
        "roles": {"central": ["central"], "compute": ["compute-1", "compute-2"]},
    }


def test_topology_loads_guests_and_roles(tmp_path):
    path = tmp_path / "topology.yaml"
    path.write_text(yaml.safe_dump(topology_data()))

    topology = Topology.from_file(path)

    assert topology.current == "central"
    assert topology.role("compute") == ["compute-1", "compute-2"]
    assert topology.hostname("compute-1") == "192.0.2.2"
    assert topology.is_local("central")
    assert not topology.is_local("compute-1")


def test_runner_executes_locally_and_over_ssh(capsys):
    calls = []

    def execute(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, "ok\n", "")

    runner = Runner(Topology(topology_data()), execute=execute)

    assert runner.run("ovn-nbctl", "show").stdout == "ok\n"
    runner.run("ip", "link", "show", guest="compute-1", input="stdin")

    assert calls[0][0] == ["ovn-nbctl", "show"]
    assert calls[1][0] == [
        "ssh",
        "-i",
        "/run/ovn-tmt-tests/multihost-driver/id_ed25519",
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=30",
        "-o",
        "LogLevel=ERROR",
        "-o",
        "StrictHostKeyChecking=no",
        "-o",
        "UserKnownHostsFile=/dev/null",
        "root@192.0.2.2",
        "ip link show",
    ]
    assert calls[1][1]["input"] == "stdin"
    assert "+ ovn-nbctl show" in capsys.readouterr().out


def test_workload_identity_is_deterministic(tmp_path):
    workload = Workload(
        FakeRunner(),
        ["compute-1", "compute-2"],
        "density-heavy",
        "dh",
        tmp_path / "metrics.csv",
    )

    endpoint = workload.endpoint(0)

    assert endpoint == {
        "guest": "compute-1",
        "namespace": "dh00000",
        "interface": "dh00000-p",
        "port": "density-heavy-00000",
        "mac": "02:00:00:00:00:01",
        "ipv4": "10.240.0.1",
        "ipv6": "fd00:240::1",
    }
    assert workload.service_name(3, "tcp", 4) == "density-heavy-00003-tcp-v4"
    assert workload.vip(3, 4) == "100.0.0.4"
    assert workload.vip(3, 6) == "100::4"


def test_workload_creates_namespace_objects(tmp_path):
    runner = FakeRunner()
    workload = Workload(
        runner,
        ["compute-1", "compute-2"],
        "density-light",
        "dl",
        tmp_path / "metrics.csv",
    )

    workload.create_topology()

    commands = [call[1] for call in runner.calls]
    assert ("ovn-nbctl", "ls-add", "density-light") in commands
    assert (
        "ovn-nbctl",
        "--bare",
        "--columns=_uuid",
        "find",
        "Logical_Switch",
        "name=density-light",
    ) in commands
    assert len([command for command in commands if "pg-add" in command]) == 3
    assert len([command for command in commands if "Address_Set" in command]) == 4


def test_workload_creates_ocp_port_state(tmp_path):
    runner = FakeRunner()
    workload = Workload(
        runner,
        ["compute-1", "compute-2"],
        "density-light",
        "dl",
        tmp_path / "metrics.csv",
    )

    workload.create_topology()
    workload.add_endpoint(0, "startup")
    workload.cleanup()

    commands = [call[1] for call in runner.calls]
    create = next(command for command in commands if "lsp-set-addresses" in command)
    assert "lsp-set-port-security" in create
    assert not [
        command for command in commands if "Port_Group" in command and "add" in command
    ]
    assert (
        "ovn-nbctl",
        "add",
        "Address_Set",
        workload.address_set_ids[1],
        "addresses",
        '"fd00:240::1"',
    ) in commands
    assert runner.batches[0][0] == "compute-1"
    assert ("ip", "netns", "add", "dl00000") in [
        command for command, _ in runner.batches[0][1]
    ]
    assert not [
        command
        for command in commands
        if any(part in {"pg-add", "pg-del", "pg-set-ports"} for part in command)
        and any(part in {"--may-exist", "--if-exists"} for part in command)
    ]


def test_workload_adds_every_service_load_balancer(tmp_path):
    runner = FakeRunner()
    workload = Workload(
        runner,
        ["compute-1", "compute-2"],
        "density-heavy",
        "dh",
        tmp_path / "metrics.csv",
    )

    workload.add_service(3, 7, ["tcp", "udp", "sctp"])

    commands = [call[1] for call in runner.calls]
    assert len([command for command in commands if "lb-add" in command]) == 6
    assert len([command for command in commands if "ls-lb-add" in command]) == 6
    assert (
        "ovn-nbctl",
        "--may-exist",
        "lb-add",
        "density-heavy-00003-tcp-v4",
        "100.0.0.4:80",
        "10.240.0.8:8080",
        "tcp",
    ) in commands
    assert (
        "ovn-nbctl",
        "--may-exist",
        "lb-add",
        "density-heavy-00003-tcp-v6",
        "[100::4]:80",
        "[fd00:240::8]:8080",
        "tcp",
    ) in commands


def test_workload_uses_shared_command_waits(tmp_path):
    runner = FakeRunner()
    workload = Workload(
        runner,
        ["compute-1", "compute-2"],
        "density-light",
        "dl",
        tmp_path / "metrics.csv",
        ipv6=False,
        timeout=3,
    )

    workload.wait_for_binding("density-light-00000")
    workload.verify_connectivity(0)

    assert runner.waits[0][0][:4] == (
        "ovn-sbctl",
        "--bare",
        "--columns=chassis",
        "find",
    )
    assert runner.waits[0][1]["interval"] == 0.2
    assert runner.waits[1] == (
        (
            "ip",
            "netns",
            "exec",
            "dl00000",
            "ping",
            "-q",
            "-c",
            "1",
            "-W",
            "1",
            "10.240.0.2",
        ),
        {
            "guest": "compute-1",
            "attempts": 3,
            "interval": 1,
        },
    )


def test_cleanup_attempts_every_object_after_a_failure(tmp_path):
    runner = FakeRunner()
    workload = Workload(
        runner,
        ["compute-1", "compute-2"],
        "density-heavy",
        "dh",
        tmp_path / "metrics.csv",
    )
    workload.endpoints = [workload.endpoint(0), workload.endpoint(1)]
    workload.load_balancers = ["lb-one", "lb-two"]
    runner.fail.add(("ovn-nbctl", "--if-exists", "lb-del", "lb-one"))

    with pytest.raises(subprocess.CalledProcessError):
        workload.cleanup()

    commands = [call[1] for call in runner.calls]
    assert ("ovn-nbctl", "--if-exists", "lb-del", "lb-two") in commands
    assert ("ovn-nbctl", "--if-exists", "ls-del", "density-heavy") in commands
    assert (
        len(
            [
                command
                for command in commands
                if "find" in command and "Port_Group" in command
            ]
        )
        == 3
    )
    assert not workload.cleaned

    runner.fail.clear()
    workload.cleanup()

    assert workload.cleaned
    completed_calls = len(runner.calls)
    workload.cleanup()
    assert len(runner.calls) == completed_calls


def test_cleanup_verification_checks_remote_endpoint_state(tmp_path):
    runner = FakeRunner()
    workload = Workload(
        runner,
        ["compute-1", "compute-2"],
        "density-light",
        "dl",
        tmp_path / "metrics.csv",
    )
    endpoint = workload.endpoint(0)
    workload.endpoints = [endpoint]
    namespace = ("ip", "netns", "exec", endpoint["namespace"], "true")
    interface = ("ovs-vsctl", "port-to-br", endpoint["interface"])
    runner.returncodes = {namespace: 1, interface: 1}

    workload.verify_cleanup()

    runner.returncodes[namespace] = 0
    with pytest.raises(AssertionError, match="network namespace remains"):
        workload.verify_cleanup()

    runner.returncodes[namespace] = 1
    runner.returncodes[interface] = 0
    with pytest.raises(AssertionError, match="OVS port remains"):
        workload.verify_cleanup()


@pytest.mark.parametrize(
    "values",
    [
        {"initial": 0},
        {"initial": 1},
        {"iterations": 0},
        {"timeout": 0},
        {"ipv4": False, "ipv6": False},
        {"ipv4": "true"},
        {"ipv6": False, "mtu": 575},
        {"mtu": 1279},
        {"mtu": 65536},
        {"chassis": 1},
        {"initial": 65534},
    ],
)
def test_light_validation_rejects_invalid_values(values):
    config = {
        "initial": 2,
        "iterations": 1,
        "timeout": 60,
        "ipv4": True,
        "ipv6": True,
        "mtu": 1280,
        "chassis": 2,
    }
    config.update(values)

    with pytest.raises(ValueError):
        validate_light(**config)


def test_light_validation_accepts_address_boundary():
    validate_light(
        initial=65533,
        iterations=1,
        timeout=60,
        ipv4=True,
        ipv6=False,
        mtu=576,
        chassis=2,
    )


@pytest.mark.parametrize(
    "values",
    [
        {"initial": 3},
        {"pods_per_service": 0},
        {"protocols": ["tcp", "http"]},
        {"protocols": ["tcp", "tcp"]},
        {"initial": 65534},
    ],
)
def test_heavy_validation_rejects_invalid_values(values):
    config = {
        "initial": 4,
        "iterations": 2,
        "pods_per_service": 2,
        "protocols": ["tcp", "udp", "sctp"],
        "timeout": 60,
        "ipv4": True,
        "ipv6": False,
        "mtu": 576,
        "chassis": 2,
    }
    config.update(values)

    with pytest.raises(ValueError):
        validate_heavy(**config)


def test_environment_configuration_is_parsed():
    environment = {
        "COUNT": "7",
        "ENABLED": "yes",
        "PROTOCOLS": "tcp, udp,sctp",
    }

    assert read_int(environment, "COUNT", 1) == 7
    assert read_bool(environment, "ENABLED", False)
    assert read_list(environment, "PROTOCOLS", "tcp") == ["tcp", "udp", "sctp"]
    assert read_int(environment, "MISSING", 3) == 3


def test_environment_integer_rejects_invalid_values():
    with pytest.raises(ValueError):
        read_int({"COUNT": "many"}, "COUNT", 1)


@pytest.mark.parametrize("value", ["maybe", "", "2"])
def test_environment_boolean_rejects_invalid_values(value):
    with pytest.raises(ValueError):
        read_bool({"ENABLED": value}, "ENABLED", True)
