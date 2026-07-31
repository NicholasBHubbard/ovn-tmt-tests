import runpy
import subprocess
from pathlib import Path
from typing import Any

import pytest
from ovn_test.workload import (
    Workload,
    load_scale_topology,
    validate_heavy,
    validate_light,
)

from ._support import FakeRunner, contains


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
    assert workload.service_name(3, "tcp", 4) == "density-heavy-00003-tcp-v4"
    assert workload.vip(3, 4) == "100.0.0.4"
    assert workload.vip(3, 6) == "100::4"


def test_loads_scale_topology_for_provisioned_guests(tmp_path: Path) -> None:
    path = tmp_path / "scale.json"
    path.write_text(
        """{
          "load_balancer_group": "cluster-lb-group",
          "workers": [
            {
              "name": "worker-0",
              "chassis": "compute-1",
              "switch": "switch-0",
              "internal": {"ipv4": "10.0.0.0/24"}
            }
          ]
        }"""
    )

    topology = load_scale_topology(path, ["compute-1", "compute-2"])

    assert topology["workers"][0]["switch"] == "switch-0"
    with pytest.raises(ValueError, match="unknown chassis"):
        load_scale_topology(path, ["compute-2"])


def test_workload_uses_prepared_scale_topology(tmp_path: Path) -> None:
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
    workload.add_service(0, 0, ["tcp"])
    workload.cleanup()

    commands = [call[1] for call in runner.calls]
    assert ("ovn-nbctl", "ls-add", "density-heavy") not in commands
    assert ("ovn-nbctl", "--if-exists", "ls-del", "density-heavy") not in commands
    assert any(
        command[:5]
        == (
            "ovn-nbctl",
            "--may-exist",
            "lsp-add",
            "switch-0",
            "density-heavy-00000",
        )
        for command in commands
    )
    assert any(
        contains(
            command,
            "add",
            "Load_Balancer_Group",
            "load-balancer-group-uuid",
            "load_balancer",
            "@lb",
        )
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
        command[:5]
        == (
            "ovn-nbctl",
            "--may-exist",
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

    workload.remove_endpoint(endpoint)
    calls_after_removal = len(runner.calls)
    batches_after_removal = len(runner.batches)
    workload.cleanup()

    assert (
        "ovn-nbctl",
        "--if-exists",
        "lsp-del",
        "cluster-density-00000",
    ) in [call[1] for call in runner.calls]
    assert endpoint["removed"]
    assert len(runner.batches) == batches_after_removal
    assert len(runner.calls) > calls_after_removal


def test_workload_adds_every_service_load_balancer(tmp_path: Path) -> None:
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
    load_balancers = [
        command for command in commands if contains(command, "create", "Load_Balancer")
    ]
    assert len(load_balancers) == 6
    command = next(
        command
        for command in load_balancers
        if 'name="density-heavy-00003-tcp-v4"' in command
    )
    assert command[:4] == (
        "ovn-nbctl",
        "--if-exists",
        "lb-del",
        "density-heavy-00003-tcp-v4",
    )
    assert 'vips:"100.0.0.4:80"="10.240.0.8:8080"' in command
    assert 'options:hairpin_snat_ip="169.254.169.5 fd69::5"' in command
    assert contains(
        command,
        "add",
        "Logical_Switch",
        "density-heavy",
        "load_balancer",
        "@lb",
    )
    command = next(
        command
        for command in load_balancers
        if 'name="density-heavy-00003-tcp-v6"' in command
    )
    assert 'vips:"[100::4]:80"="[fd00:240::8]:8080"' in command


def test_workload_reproduces_scale_background_load_balancers(tmp_path: Path) -> None:
    runner = FakeRunner()
    topology = {
        "load_balancer_group": "cluster-lb-group",
        "workers": [
            {
                "name": "worker-0",
                "chassis": "compute-1",
                "switch": "switch-0",
                "gateway_router": "gwrouter-worker-0",
                "internal": {
                    "ipv4": "10.0.0.0/24",
                    "ipv6": "fd10::/80",
                },
            },
            {
                "name": "worker-1",
                "chassis": "compute-2",
                "switch": "switch-1",
                "gateway_router": "gwrouter-worker-1",
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
        "density-heavy-base",
        "dhb",
        tmp_path / "metrics.csv",
        scale_topology=topology,
    )
    workload.endpoints = [workload.endpoint(0), workload.endpoint(1)]

    workload.add_background_load_balancers(["tcp", "udp", "sctp"])

    commands = [call[1] for call in runner.calls]
    assert len(commands) == 18
    cluster = next(
        command for command in commands if 'name="lb-cluster1-tcp"' in command
    )
    assert len([argument for argument in cluster if argument.startswith("vips:")]) == 65
    assert (
        'vips:"4.0.0.1:80"="6.0.0.1:8080,6.0.0.2:8080,10.0.0.1:8080,10.0.1.1:8080"'
    ) in cluster
    assert 'vips:"4.0.0.2:80"="6.0.0.1:8080,6.0.0.2:8080"' in cluster
    assert {argument for argument in cluster if argument.startswith("options:")} == {
        'options:event="false"',
        'options:hairpin_snat_ip="169.254.169.5 fd69::5"',
        'options:neighbor_responder="none"',
        'options:reject="true"',
        'options:skip_snat="false"',
    }
    assert contains(
        cluster,
        "add",
        "Logical_Switch",
        "switch-1",
        "load_balancer",
        "@lb",
    )
    assert contains(
        cluster,
        "add",
        "Logical_Router",
        "gwrouter-worker-1",
        "load_balancer",
        "@lb",
    )
    gateway = next(
        command for command in commands if 'name="lb-gwrouter-worker-06-tcp"' in command
    )
    assert not [argument for argument in gateway if argument.startswith("vips:")]


def test_workload_reproduces_service_route_load_balancers(
    tree: Path, tmp_path: Path
) -> None:
    runner = FakeRunner()
    topology = {
        "load_balancer_group": "cluster-lb-group",
        "workers": [
            {
                "name": "worker-0",
                "chassis": "compute-1",
                "switch": "switch-0",
                "gateway_router": "gwrouter-worker-0",
                "internal": {"ipv4": "10.0.0.0/24", "ipv6": "fd10::/80"},
                "external": {"ipv4": "172.16.0.0/24", "ipv6": "fd20::/80"},
            },
            {
                "name": "worker-1",
                "chassis": "compute-2",
                "switch": "switch-1",
                "gateway_router": "gwrouter-worker-1",
                "internal": {
                    "ipv4": "10.0.1.0/24",
                    "ipv6": "fd10:0:0:1::/80",
                },
                "external": {
                    "ipv4": "172.16.1.0/24",
                    "ipv6": "fd20:0:0:1::/80",
                },
            },
        ],
    }
    workload = Workload(
        runner,
        ["compute-1", "compute-2"],
        "service-route",
        "sr",
        tmp_path / "metrics.csv",
        scale_topology=topology,
    )
    service_route = runpy.run_path(
        str(tree / "tests/ovn-scale-testing/service-route/test.py")
    )
    endpoints = [workload.endpoint(index) for index in range(3)]

    workload.create_namespace()
    service_route["add_service_routes"](workload, 0, endpoints, ["tcp"])
    service_route["add_service_routes"](workload, 0, endpoints, ["tcp"])

    commands = [call[1] for call in runner.calls]
    created = [
        command for command in commands if contains(command, "create", "Load_Balancer")
    ]
    assert len(created) == 12
    assert len(workload.load_balancers) == 6
    cluster = next(
        command for command in created if 'name="slb-cluster-0-tcp"' in command
    )
    assert 'vips:"90.0.0.1:80"="10.0.1.1:8080,10.0.0.2:8080"' in cluster
    assert contains(
        cluster,
        "add",
        "Load_Balancer_Group",
        "load-balancer-group-uuid",
        "load_balancer",
        "@lb",
    )
    node = next(
        command for command in created if 'name="slb-node-0-worker-0-tcp"' in command
    )
    assert 'vips:"172.16.0.254:80"="10.0.1.1:8080,10.0.0.2:8080"' in node
    assert contains(
        node,
        "add",
        "Logical_Switch",
        "switch-0",
        "load_balancer",
        "@lb",
    )
    assert contains(
        node,
        "add",
        "Logical_Router",
        "gwrouter-worker-0",
        "load_balancer",
        "@lb",
    )
    assert any(
        'name="slb6-cluster-0-tcp"' in command
        and 'vips:"[9::1]:80"="[fd10:0:0:1::1]:8080,[fd10::2]:8080"' in command
        for command in created
    )

    workload.cleanup()
    workload.verify_cleanup()


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
