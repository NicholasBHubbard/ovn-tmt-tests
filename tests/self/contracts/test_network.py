import json
import subprocess
from typing import Any

from ovn_test.command import Runner
from ovn_test.network import ExternalPeers, Network
from ovn_test.topology import Topology

from ._support import FakeRunner, topology_data


def test_network_observes_namespaces_links_addresses_and_routes() -> None:
    def execute(command: Any, **kwargs: Any) -> Any:
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


def test_network_treats_a_missing_route_table_as_empty() -> None:
    def execute(command: Any, **kwargs: Any) -> Any:
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


def test_network_waits_for_ping_and_reports_failure() -> None:
    results = iter(
        [
            subprocess.CompletedProcess([], 1, "", "unreachable"),
            subprocess.CompletedProcess([], 0, "", ""),
            subprocess.CompletedProcess([], 1, "", "unreachable"),
        ]
    )
    sleeps = []
    network = Network(
        Runner(
            execute=lambda command, **kwargs: next(results),
            sleep=sleeps.append,
        )
    )

    network.wait_for_ping("vm1", "192.0.2.2", attempts=2)

    assert not network.ping("vm1", "192.0.2.3", count=2)
    assert sleeps == [1]


def test_external_peers_exercise_worker_gateway_paths() -> None:
    runner = FakeRunner()
    peers = ExternalPeers(
        runner,
        {
            "physical_bridge": "br-provider",
            "workers": [
                {
                    "name": "worker-0",
                    "chassis": "compute-1",
                    "external_vlan": 37,
                    "external": {
                        "ipv4": "172.16.0.0/24",
                        "ipv6": "fd20::/80",
                    },
                }
            ],
        },
        mtu=1400,
        timeout=3,
    )

    peers.create()
    peers.verify(
        {
            "worker": "worker-0",
            "guest": "compute-1",
            "namespace": "pod-0",
        }
    )
    peers.verify_inbound(
        {
            "worker": "worker-0",
            "guest": "compute-1",
            "ipv4": "10.0.0.1",
            "ipv6": "fd10::1",
        }
    )
    assert (
        peers.address(
            {
                "worker": "worker-0",
                "guest": "compute-1",
            },
            4,
        )
        == "172.16.0.253"
    )
    peers.cleanup()

    create_guest, create = runner.batches[0]
    assert create_guest == "compute-1"
    commands = [command for command, _ in create]
    assert (
        "ip",
        "-n",
        "dhe00000",
        "address",
        "replace",
        "172.16.0.253/24",
        "dev",
        "eth0",
    ) in commands
    assert (
        "ip",
        "-n",
        "dhe00000",
        "-6",
        "route",
        "replace",
        "default",
        "via",
        "fd20::ffff:ffff:fffe",
    ) in commands
    assert (
        "ovs-vsctl",
        "--may-exist",
        "add-port",
        "br-provider",
        "dhe00000-p",
        "--",
        "set",
        "Port",
        "dhe00000-p",
        "tag=37",
    ) in commands
    assert [wait[0][-1] for wait in runner.waits] == [
        "172.16.0.253",
        "fd20::ffff:ffff:fffd",
        "10.0.0.1",
        "fd10::1",
    ]
    assert runner.waits[-1][0][3] == "dhe00000"

    runner.returncodes[("ip", "netns", "exec", "dhe00000", "true")] = 1
    runner.returncodes[("ovs-vsctl", "port-to-br", "dhe00000-p")] = 1
    peers.verify_cleanup()
