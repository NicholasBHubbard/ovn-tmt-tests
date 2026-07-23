import json
import subprocess
from pathlib import Path

import pytest

from ovn_test.ansible import Ansible
from ovn_test.command import Runner
from ovn_test.files import find_text
from ovn_test.network import Network
from ovn_test.ovsdb import Ovsdb
from ovn_test.state import Snapshots
from ovn_test.system import processes, tcp_listeners
from ovn_test.topology import Topology

from .test_ovn_test import topology_data


def test_runner_conveniences(capsys):
    calls = []
    responses = iter(
        [
            subprocess.CompletedProcess([], 0, " value \n", ""),
            subprocess.CompletedProcess([], 0, "raw\n", ""),
            subprocess.CompletedProcess([], 0, "", ""),
        ]
    )

    def execute(command, **kwargs):
        calls.append((command, kwargs))
        return next(responses)

    runner = Runner(Topology(topology_data()), execute=execute)

    assert runner.output("get-value", cwd="/work", env={"EXAMPLE": "value"}) == "value"
    assert runner.output("get-raw", strip=False) == "raw\n"
    runner.namespace("sandbox", "ip", "link", "show")

    assert calls[2][0] == [
        "ip",
        "netns",
        "exec",
        "sandbox",
        "ip",
        "link",
        "show",
    ]
    assert calls[0][1]["cwd"] == "/work"
    assert calls[0][1]["env"] == {"EXAMPLE": "value"}
    assert "+ ip netns exec sandbox ip link show" in capsys.readouterr().out


def test_runner_reports_command_success():
    runner = Runner(
        Topology(topology_data()),
        execute=lambda command, **kwargs: subprocess.CompletedProcess(
            command, int(command == ["false"]), "", ""
        ),
    )

    assert runner.succeeds("true")
    assert not runner.succeeds("false")


def test_runner_reports_missing_commands_as_unsuccessful():
    def execute(command, **kwargs):
        raise FileNotFoundError(command[0])

    assert not Runner(execute=execute).succeeds("missing")


def test_runner_does_not_require_topology_for_local_commands():
    runner = Runner(
        execute=lambda command, **kwargs: subprocess.CompletedProcess(
            command, 0, "local\n", ""
        )
    )

    assert runner.output("hostname") == "local"
    with pytest.raises(ValueError, match="topology"):
        runner.run("hostname", guest="compute-1")


def test_runner_normalizes_arguments_and_wait_options():
    calls = []

    def execute(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, "", "")

    runner = Runner(execute=execute)

    runner.run(Path("/usr/bin/true"), 1)
    runner.wait(
        "probe",
        attempts=1,
        cwd="/work",
        env={"EXAMPLE": "value"},
    )

    assert calls[0][0] == ["/usr/bin/true", "1"]
    assert calls[1][1]["cwd"] == "/work"
    assert calls[1][1]["env"] == {"EXAMPLE": "value"}


def test_runner_waits_for_a_result():
    results = iter(
        [
            subprocess.CompletedProcess([], 1, "", "not yet\n"),
            subprocess.CompletedProcess([], 0, "", ""),
            subprocess.CompletedProcess([], 0, "ready\n", ""),
        ]
    )
    sleeps = []

    runner = Runner(
        Topology(topology_data()),
        execute=lambda command, **kwargs: next(results),
        sleep=sleeps.append,
    )

    result = runner.wait(
        "probe",
        attempts=3,
        interval=0.25,
        until=lambda completed: completed.stdout.strip() == "ready",
    )

    assert result.stdout == "ready\n"
    assert sleeps == [0.25, 0.25]


def test_runner_wait_reports_timeout():
    calls = 0

    def execute(command, **kwargs):
        nonlocal calls
        calls += 1
        return subprocess.CompletedProcess(command, 1, "", "still unavailable\n")

    runner = Runner(
        Topology(topology_data()),
        execute=execute,
        sleep=lambda interval: None,
    )

    with pytest.raises(TimeoutError, match=r"probe.*3 attempts"):
        runner.wait("probe", attempts=3, interval=0)
    assert calls == 3

    with pytest.raises(ValueError, match="attempts"):
        runner.wait("probe", attempts=0)


def test_find_text_recurses_and_reports_matching_files(tmp_path):
    nested = tmp_path / "nested"
    nested.mkdir()
    match = nested / "match.fmf"
    match.write_text("OTT_EXAMPLE: value\n")
    (tmp_path / "other.txt").write_text("nothing here\n")
    (tmp_path / "binary").write_bytes(b"\xffOTT_EXAMPLE")

    assert find_text(tmp_path, "OTT_EXAMPLE") == [tmp_path / "binary", match]
    assert find_text(match, "missing") == []
    with pytest.raises(FileNotFoundError):
        find_text(tmp_path / "missing", "anything")


def test_snapshots_preserve_values(tmp_path):
    snapshots = Snapshots(tmp_path)

    assert snapshots.save("port-id", "uuid-1") == "uuid-1"
    assert snapshots.load("port-id") == "uuid-1"
    assert snapshots.path("port-id") == tmp_path / "port-id"

    with pytest.raises(ValueError, match="snapshot name"):
        snapshots.save("../outside", "bad")


def test_snapshots_use_tmt_test_data(tmp_path):
    snapshots = Snapshots.from_environment({"TMT_TEST_DATA": str(tmp_path)})

    snapshots.save("switch-id", "uuid-2")

    assert (tmp_path / "snapshots" / "switch-id").read_text() == "uuid-2"


def test_snapshots_prefer_stable_tmt_plan_data(tmp_path):
    plan_data = tmp_path / "plan"
    test_data = tmp_path / "test"
    snapshots = Snapshots.from_environment(
        {
            "TMT_PLAN_DATA": str(plan_data),
            "TMT_TEST_DATA": str(test_data),
        }
    )

    snapshots.save("switch-id", "uuid-3")

    assert (plan_data / "snapshots" / "switch-id").read_text() == "uuid-3"
    assert not test_data.exists()


def test_snapshots_accept_tmt_plan_data_without_test_data(tmp_path):
    snapshots = Snapshots.from_environment({"TMT_PLAN_DATA": str(tmp_path)})

    snapshots.save("switch-id", "uuid-4")

    assert (tmp_path / "snapshots" / "switch-id").read_text() == "uuid-4"


def test_ovsdb_decodes_json_rows():
    payload = {
        "headings": ["name", "ports", "external_ids", "_uuid"],
        "data": [
            [
                "sw0",
                ["set", [["uuid", "port-1"], ["uuid", "port-2"]]],
                ["map", [["owner", "test"], ["enabled", True]]],
                ["uuid", "switch-1"],
            ]
        ],
    }
    calls = []

    class FakeRunner:
        def output(self, *command, **kwargs):
            calls.append((command, kwargs))
            return json.dumps(payload)

    database = Ovsdb(FakeRunner(), "ovn-nbctl")

    rows = database.find(
        "Logical_Switch",
        "name=sw0",
        columns=("name", "ports", "external_ids", "_uuid"),
    )

    assert rows == [
        {
            "name": "sw0",
            "ports": ["port-1", "port-2"],
            "external_ids": {"owner": "test", "enabled": True},
            "_uuid": "switch-1",
        }
    ]
    assert (
        database.one(
            "Logical_Switch",
            "name=sw0",
            columns=("name",),
        )["name"]
        == "sw0"
    )
    assert database.value("Logical_Switch", "name", "name=sw0") == "sw0"
    assert database.exists("Logical_Switch", "name=sw0")
    assert calls[0][0] == (
        "ovn-nbctl",
        "--format=json",
        "--data=json",
        "--columns=name,ports,external_ids,_uuid",
        "find",
        "Logical_Switch",
        "name=sw0",
    )


def test_ovsdb_one_requires_exactly_one_row():
    class FakeRunner:
        def __init__(self, rows):
            self.rows = rows

        def output(self, *command, **kwargs):
            return json.dumps({"headings": ["name"], "data": self.rows})

    with pytest.raises(LookupError, match="found 0"):
        Ovsdb(FakeRunner([]), "ovn-nbctl").one(
            "Logical_Switch", "name=missing", columns=("name",)
        )
    assert not Ovsdb(FakeRunner([]), "ovn-nbctl").exists(
        "Logical_Switch", "name=missing"
    )
    with pytest.raises(LookupError, match="found 2"):
        Ovsdb(FakeRunner([["one"], ["two"]]), "ovn-nbctl").one(
            "Logical_Switch", columns=("name",)
        )


def test_network_observes_namespaces_links_addresses_and_routes():
    def execute(command, **kwargs):
        if command == ["ip", "netns", "exec", "vm1", "true"]:
            return subprocess.CompletedProcess(command, 0, "", "")
        if command == ["ip", "netns", "exec", "missing", "true"]:
            return subprocess.CompletedProcess(command, 1, "", "")
        if command == [
            "ip",
            "-j",
            "-n",
            "vm1",
            "link",
            "show",
            "dev",
            "missing",
        ]:
            return subprocess.CompletedProcess(command, 1, "", "")
        if command == [
            "ip",
            "-j",
            "-n",
            "vm1",
            "link",
            "show",
            "dev",
            "eth0",
        ]:
            stdout = json.dumps([{"ifname": "eth0", "mtu": 1400}])
        elif command == [
            "ip",
            "-j",
            "-n",
            "vm1",
            "address",
            "show",
            "dev",
            "eth0",
        ]:
            stdout = json.dumps(
                [
                    {
                        "addr_info": [
                            {
                                "local": "192.0.2.10",
                                "prefixlen": 24,
                                "scope": "global",
                            },
                            {
                                "local": "fe80::1",
                                "prefixlen": 64,
                                "scope": "link",
                            },
                        ]
                    }
                ]
            )
        elif command == [
            "ip",
            "-j",
            "-n",
            "vm1",
            "-4",
            "route",
            "show",
            "table",
            "101",
            "198.51.100.0/24",
        ]:
            stdout = json.dumps(
                [
                    {
                        "dst": "198.51.100.0/24",
                        "gateway": "192.0.2.2",
                        "dev": "eth0",
                        "metric": 20,
                    }
                ]
            )
        else:
            raise AssertionError(command)
        return subprocess.CompletedProcess(command, 0, stdout, "")

    runner = Runner(Topology(topology_data()), execute=execute)
    network = Network(runner)

    assert network.namespace_exists("vm1")
    assert not network.namespace_exists("missing")
    assert network.link("eth0", namespace="vm1") == {
        "ifname": "eth0",
        "mtu": 1400,
    }
    assert network.link("missing", namespace="vm1") is None
    assert network.addresses("eth0", namespace="vm1", scope="global") == [
        "192.0.2.10/24"
    ]
    assert network.routes(
        namespace="vm1",
        family=4,
        table=101,
        destination="198.51.100.0/24",
    ) == [
        {
            "dst": "198.51.100.0/24",
            "gateway": "192.0.2.2",
            "dev": "eth0",
            "metric": 20,
        }
    ]


def test_network_treats_a_missing_route_table_as_empty():
    def execute(command, **kwargs):
        result = subprocess.CompletedProcess(
            command,
            2,
            "[]\n",
            "Error: ipv4: FIB table does not exist.\nDump terminated\n",
        )
        if kwargs["check"]:
            raise subprocess.CalledProcessError(
                result.returncode,
                command,
                result.stdout,
                result.stderr,
            )
        return result

    network = Network(Runner(execute=execute))

    assert (
        network.routes(
            namespace="vm1",
            family=4,
            table=100,
        )
        == []
    )


def test_system_observes_exact_processes_and_tcp_ports():
    calls = []

    def execute(command, **kwargs):
        calls.append(command)
        if command[0] == "pgrep":
            return subprocess.CompletedProcess(command, 0, "10 ovn-controller\n", "")
        return subprocess.CompletedProcess(
            command, 0, "LISTEN 0 128 0.0.0.0:6641\n", ""
        )

    runner = Runner(Topology(topology_data()), execute=execute)

    assert processes(runner, "ovn-controller") == ["10 ovn-controller"]
    assert tcp_listeners(runner, 6641) == ["LISTEN 0 128 0.0.0.0:6641"]
    assert calls == [
        ["pgrep", "-a", "-x", "ovn-controller"],
        ["ss", "-H", "-ltn", "sport = :6641"],
    ]


def test_process_observation_distinguishes_absence_from_error():
    status = 1

    def execute(command, **kwargs):
        return subprocess.CompletedProcess(command, status, "", "error")

    runner = Runner(Topology(topology_data()), execute=execute)

    assert processes(runner, "ovn-controller") == []
    status = 2
    with pytest.raises(subprocess.CalledProcessError):
        processes(runner, "ovn-controller")


def test_ansible_writes_inventory_and_keeps_per_guest_logs(tmp_path):
    calls = []

    def execute(command, **kwargs):
        calls.append((command, kwargs))
        guest = command[command.index("--limit") + 1]
        status = 7 if guest == "compute-1" else 0
        return subprocess.CompletedProcess(
            command,
            status,
            f"TASK [{guest}]\n",
            f"stderr-{guest}\n",
        )

    data = tmp_path / "data"
    ansible = Ansible(
        Topology(topology_data()),
        tree=tmp_path,
        data=data,
        execute=execute,
        environment={"OTT_TEST_DEBUG": "true"},
    )

    with pytest.raises(subprocess.CalledProcessError) as error:
        ansible.run("setup.yml", "-e", "example=true")

    assert error.value.returncode == 7
    inventory = (data / "ansible-inventory.ini").read_text()
    assert "[all]" in inventory
    assert "compute-1 ansible_host=192.0.2.2" in inventory
    assert "[compute]\ncompute-1\ncompute-2\n" in inventory
    assert len(calls) == 3
    assert all("-vvv" in command for command, kwargs in calls)
    assert all(kwargs["cwd"] == tmp_path for command, kwargs in calls)
    assert all(
        kwargs["env"]["ANSIBLE_ROLES_PATH"] == str(tmp_path / "roles")
        for command, kwargs in calls
    )
    assert "TASK [compute-1]" in (data / "setup-compute-1.log").read_text()
    combined = (data / "setup.log").read_text()
    assert "===== central =====" in combined
    assert "===== compute-1 =====" in combined


def test_ansible_uses_tmt_environment_paths(tmp_path):
    environment = {
        "TMT_TREE": str(tmp_path / "tree"),
        "TMT_TEST_DATA": str(tmp_path / "data"),
    }

    ansible = Ansible.from_environment(
        topology=Topology(topology_data()),
        execute=lambda command, **kwargs: subprocess.CompletedProcess(
            command, 0, "", ""
        ),
        environment=environment,
    )

    assert ansible.tree == tmp_path / "tree"
    assert ansible.data == tmp_path / "data"
