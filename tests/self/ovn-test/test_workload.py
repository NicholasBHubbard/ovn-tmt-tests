import json
import subprocess
from pathlib import Path
from typing import Any, Optional

import pytest
from ovn_test.command import Runner
from ovn_test.workload import (
    Workload,
    validate_heavy,
    validate_light,
)


class FakeRunner(Runner):
    def __init__(self) -> None:
        self.calls = []
        self.batches = []
        self.fail = set()
        self.outputs = {}
        self.returncodes = {}
        self.waits = []

    def run(
        self,
        *command: Any,
        guest: Optional[str] = None,
        input: Any = None,
        check: bool = True,
        cwd: Any = None,
        env: Any = None,
        announce: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        self.calls.append((guest, command, input))
        if command in self.fail:
            raise subprocess.CalledProcessError(1, command)
        stdout = ""
        if command[:3] in {
            ("ovn-nbctl", "create", "Address_Set"),
            ("ovn-nbctl", "create", "Port_Group"),
        }:
            stdout = f"uuid-{len(self.calls)}\n"
        if command[:4] == ("ovn-nbctl", "--id=@lb", "create", "Load_Balancer"):
            stdout = f"load-balancer-{len(self.calls)}\n"
        if "Load_Balancer_Group" in command and "--columns=_uuid" in command:
            stdout = "load-balancer-group-uuid\n"
        if "Logical_Switch" in command and command[-1] in {
            'name="switch-0"',
            'name="switch-1"',
        }:
            stdout = "logical-switch-uuid\n"
        if "Port_Binding" in command:
            stdout = "chassis-uuid\n"
        stdout = self.outputs.get((guest, command), stdout)
        return subprocess.CompletedProcess(
            command,
            self.returncodes.get(command, 0),
            stdout,
            "",
        )

    def output(self, *command: Any, **options: Any) -> str:
        return self.run(*command, **options).stdout.strip()

    def namespace(
        self, namespace: str, *command: Any, **options: Any
    ) -> subprocess.CompletedProcess[str]:
        return self.run("ip", "netns", "exec", namespace, *command, **options)

    def run_many(
        self, commands: Any, guest: Optional[str] = None
    ) -> subprocess.CompletedProcess[str]:
        self.batches.append((guest, commands))
        return subprocess.CompletedProcess([], 0, "", "")

    def wait(self, *command: Any, **options: Any) -> subprocess.CompletedProcess[str]:
        self.waits.append((command, options))
        result = self.run(*command, check=False, guest=options.get("guest"))
        condition = options.get("until")
        if condition is not None and not condition(result):
            raise TimeoutError(command)
        return result


def find_uuids(table: str, name: str, owner: Optional[str] = None) -> tuple[str, ...]:
    command = (
        "ovn-nbctl",
        "--bare",
        "--columns=_uuid",
        "find",
        table,
        f"name={json.dumps(name)}",
    )
    if owner is not None:
        command += (f"external_ids:ovn-tmt-tests-owner={json.dumps(owner)}",)
    return command


def test_workload_identity_is_deterministic(tmp_path: Path) -> None:
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


@pytest.mark.parametrize(
    "overrides",
    (
        {"computes": []},
        {"computes": ["compute-1", "compute-1"]},
        {"name": "bad name"},
        {"prefix": "too-long-"},
        {"integration_bridge": "bridge-name-is-too-long"},
        {"ipv4": False, "ipv6": False},
        {"mtu": 0},
        {"timeout": 0},
        {"sync_timeout": 0},
        {"ipv4_network": "fd00::/64"},
        {"ipv6_network": "10.0.0.0/24"},
    ),
)
def test_workload_rejects_invalid_configuration_before_writing_metrics(
    tmp_path: Path, overrides: dict[str, Any]
) -> None:
    metrics = tmp_path / "metrics.csv"
    options: dict[str, Any] = {
        "runner": FakeRunner(),
        "computes": ["compute-1"],
        "name": "workload",
        "prefix": "wl",
        "metrics_file": metrics,
        **overrides,
    }

    with pytest.raises(ValueError, match=r".+"):
        Workload(**options)

    assert not metrics.exists()


def test_workload_copies_and_validates_scale_topology(tmp_path: Path) -> None:
    computes = ["compute-1"]
    worker = {
        "name": "worker-0",
        "chassis": "compute-1",
        "switch": "switch-0",
        "internal": {"ipv4": "10.0.0.0/24", "ipv6": "fd10::/80"},
    }
    workload = Workload(
        FakeRunner(),
        computes,
        "workload",
        "wl",
        tmp_path / "metrics.csv",
        scale_topology={"workers": [worker]},
    )

    computes[0] = "changed"
    worker["chassis"] = "changed"
    worker["internal"]["ipv4"] = "192.0.2.0/24"

    assert workload.endpoint(0)["guest"] == "compute-1"
    assert workload.endpoint(0)["ipv4"] == "10.0.0.1"

    with pytest.raises(ValueError, match="unknown compute"):
        Workload(
            FakeRunner(),
            ["compute-1"],
            "invalid",
            "iv",
            tmp_path / "invalid.csv",
            scale_topology={
                "workers": [
                    {
                        **worker,
                        "chassis": "compute-2",
                    }
                ]
            },
        )


def test_workload_uses_configured_bridge_and_networks(tmp_path: Path) -> None:
    runner = FakeRunner()
    workload = Workload(
        runner,
        ["compute-1"],
        "workload",
        "wl",
        tmp_path / "metrics.csv",
        integration_bridge="br-ovn",
        ipv4_network="192.0.2.0/24",
        ipv6_network="2001:db8::/120",
    )

    endpoint = workload.add_endpoint(0, "test", converge=False)

    assert endpoint["ipv4"] == "192.0.2.1"
    assert endpoint["ipv6"] == "2001:db8::1"
    commands = [command for command, _ in runner.batches[0][1]]
    assert ("ovs-vsctl", "--if-exists", "del-port", "br-ovn", "wl00000-p") in commands
    assert any(
        command[:4] == ("ovs-vsctl", "--may-exist", "add-port", "br-ovn")
        for command in commands
    )
    assert (
        "ip",
        "-n",
        "wl00000",
        "address",
        "replace",
        "192.0.2.1/24",
        "dev",
        "eth0",
    ) in commands


def test_workload_uses_scale_topology(tmp_path: Path) -> None:
    runner = FakeRunner()
    topology = {
        "load_balancer_group": "cluster-lb-group",
        "workers": [
            {
                "name": "worker-0",
                "chassis": "compute-1",
                "switch": "switch-0",
                "internal": {
                    "ipv4": "10.0.0.0/24",
                    "ipv6": "fd10::/80",
                },
            },
            {
                "name": "worker-1",
                "chassis": "compute-2",
                "switch": "switch-1",
                "internal": {
                    "ipv4": "10.0.1.0/24",
                    "ipv6": "fd10:0:0:1::/80",
                },
            },
        ],
    }
    workload = Workload(
        runner,
        ["compute-1", "compute-2"],
        "density-heavy",
        "dh",
        tmp_path / "metrics.csv",
        scale_topology=topology,
    )

    assert workload.endpoint(0)["guest"] == "compute-1"
    assert workload.endpoint(0)["switch"] == "switch-0"
    assert workload.endpoint(0)["ipv4"] == "10.0.0.1"
    assert workload.endpoint(0)["gateway4"] == "10.0.0.254"
    assert workload.endpoint(0)["prefix4"] == 24
    assert workload.endpoint(1)["guest"] == "compute-2"
    assert workload.endpoint(1)["ipv4"] == "10.0.1.1"
    assert workload.endpoint(2)["ipv4"] == "10.0.0.2"

    workload.create_namespace()
    workload.add_endpoint(0, "iteration")
    assert workload.load_balancer_group_id() == "load-balancer-group-uuid"
    workload.cleanup()

    commands = [call[1] for call in runner.calls]
    assert ("ovn-nbctl", "ls-add", "density-heavy") not in commands
    assert ("ovn-nbctl", "--if-exists", "ls-del", "density-heavy") not in commands
    assert any(
        command[:4] == ("ovn-nbctl", "lsp-add", "switch-0", "density-heavy-00000")
        for command in commands
    )
    guest, batch = runner.batches[0]
    assert guest == "compute-1"
    assert (
        "ip",
        "-n",
        "dh00000",
        "route",
        "replace",
        "default",
        "via",
        "10.0.0.254",
    ) in [command for command, _ in batch]


def test_workload_reserves_base_worker_addresses_and_identities(tmp_path: Path) -> None:
    topology = {
        "load_balancer_group": "cluster-lb-group",
        "workers": [
            {
                "name": "worker-0",
                "chassis": "compute-1",
                "switch": "switch-0",
                "internal": {
                    "ipv4": "10.0.0.0/24",
                    "ipv6": "fd10::/80",
                },
            },
            {
                "name": "worker-1",
                "chassis": "compute-2",
                "switch": "switch-1",
                "internal": {
                    "ipv4": "10.0.1.0/24",
                    "ipv6": "fd10:0:0:1::/80",
                },
            },
        ],
    }
    workload = Workload(
        FakeRunner(),
        ["compute-1", "compute-2"],
        "density-heavy",
        "dh",
        tmp_path / "metrics.csv",
        scale_topology=topology,
        base_ports_per_worker=10,
    )

    assert workload.endpoint(0)["ipv4"] == "10.0.0.11"
    assert workload.endpoint(1)["ipv4"] == "10.0.1.11"
    assert workload.endpoint(0)["mac"] == "02:00:00:00:00:15"


def test_workload_base_ports_do_not_require_namespace_state(tmp_path: Path) -> None:
    runner = FakeRunner()
    topology = {
        "load_balancer_group": "cluster-lb-group",
        "workers": [
            {
                "name": "worker-0",
                "chassis": "compute-1",
                "switch": "switch-0",
                "internal": {
                    "ipv4": "10.0.0.0/24",
                    "ipv6": "fd10::/80",
                },
            }
        ],
    }
    workload = Workload(
        runner,
        ["compute-1"],
        "density-heavy-base",
        "dhb",
        tmp_path / "metrics.csv",
        scale_topology=topology,
    )

    workload.add_endpoint(0, "base", passive=True)

    commands = [call[1] for call in runner.calls]
    assert not [
        command
        for command in commands
        if len(command) > 3 and command[:3] == ("ovn-nbctl", "add", "Address_Set")
    ]
    assert any(
        command[:4]
        == (
            "ovn-nbctl",
            "lsp-add",
            "switch-0",
            "density-heavy-base-00000",
        )
        for command in commands
    )


def test_workload_creates_namespace_objects(tmp_path: Path) -> None:
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
    assert any(
        command[:3] == ("ovn-nbctl", "ls-add", "density-light")
        and 'external_ids:ovn-tmt-tests-owner="density-light"' in command
        for command in commands
    )
    assert (
        len(
            [
                command
                for command in commands
                if command[:3] == ("ovn-nbctl", "create", "Port_Group")
            ]
        )
        == 3
    )
    assert (
        len(
            [
                command
                for command in commands
                if command[:3] == ("ovn-nbctl", "create", "Address_Set")
            ]
        )
        == 2
    )


def test_workload_creates_ocp_port_state(tmp_path: Path) -> None:
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


def test_workload_creates_passive_port_without_namespace(tmp_path: Path) -> None:
    runner = FakeRunner()
    workload = Workload(
        runner,
        ["compute-1", "compute-2"],
        "density-heavy",
        "dh",
        tmp_path / "metrics.csv",
    )

    workload.create_topology()
    workload.add_endpoint(0, "startup", passive=True)

    guest, commands = runner.batches[0]
    commands = [command for command, _ in commands]
    assert guest == "compute-1"
    assert ("ip", "netns", "add", "dh00000") not in commands
    assert not [command for command in commands if "veth" in command]
    assert (
        "ovs-vsctl",
        "--may-exist",
        "add-port",
        "br-int",
        "dh00000-p",
        "--",
        "set",
        "Interface",
        "dh00000-p",
        "type=internal",
        "external_ids:iface-id=density-heavy-00000",
    ) in commands
    assert runner.waits[0][0][-1] == "logical_port=density-heavy-00000"


def test_workload_can_defer_endpoint_convergence(tmp_path: Path) -> None:
    runner = FakeRunner()
    workload = Workload(
        runner,
        ["compute-1", "compute-2"],
        "density-heavy",
        "dh",
        tmp_path / "metrics.csv",
        sync_timeout=1800,
    )

    workload.add_endpoint(0, "startup", passive=True, converge=False)

    sync = ("ovn-nbctl", "--wait=hv", "--timeout=1800", "sync")
    assert not runner.waits
    assert sync not in [call[1] for call in runner.calls]

    workload.sync()

    assert sync in [call[1] for call in runner.calls]


def test_workload_removes_logical_and_local_endpoint_state(tmp_path: Path) -> None:
    runner = FakeRunner()
    workload = Workload(
        runner,
        ["compute-1", "compute-2"],
        "cluster-density",
        "cd",
        tmp_path / "metrics.csv",
    )
    endpoint = workload.add_endpoint(0, "iteration", converge=False)
    runner.outputs[(None, find_uuids("Logical_Switch_Port", endpoint["port"]))] = (
        "endpoint-uuid"
    )
    runner.outputs[
        (
            None,
            find_uuids("Logical_Switch_Port", endpoint["port"], "cluster-density"),
        )
    ] = "endpoint-uuid"

    workload.remove_endpoint(endpoint)
    calls_after_removal = len(runner.calls)
    batches_after_removal = len(runner.batches)
    workload.cleanup()

    assert (
        "ovn-nbctl",
        "lsp-del",
        "endpoint-uuid",
    ) in [call[1] for call in runner.calls]
    assert endpoint["removed"]
    assert len(runner.batches) == batches_after_removal
    assert len(runner.calls) > calls_after_removal


def test_workload_rejects_foreign_name_collisions(tmp_path: Path) -> None:
    runner = FakeRunner()
    workload = Workload(
        runner,
        ["compute-1"],
        "shared-name",
        "sn",
        tmp_path / "metrics.csv",
    )
    runner.outputs[(None, find_uuids("Logical_Switch", "shared-name"))] = "foreign-uuid"

    with pytest.raises(RuntimeError, match="another topology"):
        workload.create_topology()

    assert not any(
        command[:3] == ("ovn-nbctl", "ls-add", "shared-name")
        for _, command, _ in runner.calls
    )


def test_workload_tracks_endpoint_lifecycle(tmp_path: Path) -> None:
    workload = Workload(
        FakeRunner(),
        ["compute-1"],
        "workload",
        "wl",
        tmp_path / "metrics.csv",
    )
    endpoint = workload.add_endpoint(0, "test", converge=False)

    with pytest.raises(RuntimeError, match="already exists"):
        workload.add_endpoint(0, "test", converge=False)
    with pytest.raises(ValueError, match="not owned"):
        workload.remove_endpoint(workload.endpoint(1))

    workload.remove_endpoint(endpoint)
    replacement = workload.add_endpoint(0, "test", converge=False)

    assert replacement is not endpoint


def test_cleaned_workload_rejects_mutation(tmp_path: Path) -> None:
    workload = Workload(
        FakeRunner(),
        ["compute-1"],
        "workload",
        "wl",
        tmp_path / "metrics.csv",
    )
    workload.cleanup()

    for action in (
        workload.create_namespace,
        lambda: workload.add_endpoint(0, "test"),
        lambda: workload.replace_load_balancer("lb", "tcp"),
    ):
        with pytest.raises(RuntimeError, match="cleaned"):
            action()


def test_workload_metrics_use_monotonic_time(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workload = Workload(
        FakeRunner(),
        ["compute-1"],
        "workload",
        "wl",
        tmp_path / "metrics.csv",
    )
    ticks = iter((100, 175))
    monkeypatch.setattr("ovn_test.workload.time.monotonic_ns", lambda: next(ticks))

    assert workload.measure(1, "phase", lambda: "result") == "result"
    assert workload.metrics_file.read_text(encoding="utf-8").splitlines()[-1] == (
        "1,phase,75"
    )


def test_workload_uses_shared_command_waits(tmp_path: Path) -> None:
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
    workload.verify_connectivity(2, 3)

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
    assert runner.waits[2][0][-1] == "10.240.0.4"


def test_cleanup_attempts_every_object_after_a_failure(tmp_path: Path) -> None:
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
    find_managed = (
        "ovn-nbctl",
        "--format=csv",
        "--data=bare",
        "--no-headings",
        "--columns=_uuid,name",
        "find",
        "Load_Balancer",
        'external_ids:ovn-tmt-tests-owner="density-heavy"',
    )
    runner.outputs[(None, find_managed)] = "lb-one-uuid,lb-one\nlb-two-uuid,lb-two\n"
    runner.fail.add(("ovn-nbctl", "destroy", "Load_Balancer", "lb-one-uuid"))

    with pytest.raises(subprocess.CalledProcessError):
        workload.cleanup()

    commands = [call[1] for call in runner.calls]
    assert ("ovn-nbctl", "destroy", "Load_Balancer", "lb-two-uuid") in commands
    assert find_uuids("Logical_Switch", "density-heavy", "density-heavy") in commands
    assert any(
        "Port_Group" in command
        and 'external_ids:ovn-tmt-tests-owner="density-heavy"' in command
        for command in commands
    )
    assert not workload.cleaned

    runner.fail.clear()
    workload.cleanup()

    assert workload.cleaned
    completed_calls = len(runner.calls)
    workload.cleanup()
    assert len(runner.calls) == completed_calls


def test_cleanup_verification_checks_remote_endpoint_state(tmp_path: Path) -> None:
    runner = FakeRunner()
    workload = Workload(
        runner,
        ["compute-1", "compute-2"],
        "density-light",
        "dl",
        tmp_path / "metrics.csv",
    )
    endpoints = [workload.endpoint(0), workload.endpoint(1)]
    workload.endpoints = endpoints
    namespaces = ("ip", "netns", "list")
    ports = ("ovs-vsctl", "list-ports", "br-int")

    workload.verify_cleanup()
    snapshot_calls = [
        (guest, command)
        for guest, command, _ in runner.calls
        if command in {namespaces, ports}
    ]
    assert snapshot_calls == [
        ("compute-1", namespaces),
        ("compute-1", ports),
        ("compute-2", namespaces),
        ("compute-2", ports),
    ]

    first = endpoints[0]
    runner.outputs[("compute-1", namespaces)] = (
        f"{first['namespace']} (id: 7)\nunrelated\n"
    )
    with pytest.raises(AssertionError, match="network namespace remains"):
        workload.verify_cleanup()

    runner.outputs[("compute-1", namespaces)] = "unrelated\n"
    runner.outputs[("compute-1", ports)] = f"{first['interface']}\nunrelated-p\n"
    with pytest.raises(AssertionError, match="OVS port remains"):
        workload.verify_cleanup()


@pytest.mark.parametrize(
    "values",
    (
        {"initial": 0},
        {"initial": "2"},
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
    ),
)
def test_light_validation_rejects_invalid_values(values: Any) -> None:
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

    with pytest.raises(ValueError, match=r".+"):
        validate_light(**config)


def test_light_validation_accepts_address_boundary() -> None:
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
    (
        {"initial": 3},
        {"pods_per_service": 0},
        {"protocols": ["tcp", "http"]},
        {"protocols": "tcp"},
        {"protocols": None},
        {"protocols": [["tcp"]]},
        {"protocols": ["tcp", "tcp"]},
        {"initial": 65534},
    ),
)
def test_heavy_validation_rejects_invalid_values(values: Any) -> None:
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

    with pytest.raises(ValueError, match=r".+"):
        validate_heavy(**config)
