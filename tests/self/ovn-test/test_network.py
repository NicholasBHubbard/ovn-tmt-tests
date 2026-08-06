import json
import subprocess
from collections.abc import Callable
from typing import Any
from unittest.mock import Mock

import pytest
from ovn_test.command import Runner
from ovn_test.network import ExternalPeers, Network
from ovn_test.topology import Topology


def _worker(
    name: str = "worker-0",
    chassis: str = "compute-1",
    **values: Any,
) -> dict[str, Any]:
    worker = {
        "name": name,
        "chassis": chassis,
        "external": {"ipv4": "192.0.2.0/24", "ipv6": "2001:db8::/64"},
    }
    worker.update(values)
    return worker


def _topology(*workers: object) -> dict[str, Any]:
    return {
        "physical_bridge": "br-provider",
        "workers": list(workers or (_worker(),)),
    }


def test_network_rejects_invalid_arguments_before_running_commands() -> None:
    runner = Mock(spec=Runner)
    network = Network(runner)
    invalid: tuple[tuple[Callable[[], object], str], ...] = (
        (lambda: Network(runner, ""), "guest"),
        (lambda: network.namespace_exists(""), "namespace"),
        (lambda: network.ping("namespace", ""), "destination"),
        (lambda: network.ping("namespace", "host", count=0), "count"),
        (lambda: network.ping("namespace", "host", timeout=True), "timeout"),
        (lambda: network.wait_for_ping("namespace", "host", 0), "attempts"),
        (lambda: network.link(""), "interface"),
        (lambda: network.addresses("eth0", scope=""), "scope"),
        (lambda: network.routes(family=5), "family"),
        (lambda: network.routes(table=-1), "route table"),
        (lambda: network.routes(table=True), "route table"),
        (lambda: network.routes(table=""), "route table"),
        (lambda: network.routes(destination=""), "destination"),
    )

    for action, message in invalid:
        with pytest.raises(ValueError, match=message):
            action()
    runner.run.assert_not_called()
    runner.output.assert_not_called()
    runner.namespace.assert_not_called()
    runner.wait.assert_not_called()


@pytest.mark.parametrize("output", ("not-json", "{}", "[1]"))
def test_network_rejects_invalid_ip_json(output: str) -> None:
    runner = Mock(spec=Runner)
    runner.run.return_value = subprocess.CompletedProcess(["ip"], 0, output, "")

    with pytest.raises(RuntimeError, match="invalid"):
        Network(runner).link("eth0")


def test_network_can_require_an_existing_link() -> None:
    runner = Mock(spec=Runner)
    runner.run.return_value = subprocess.CompletedProcess(["ip"], 1, "", "missing")

    with pytest.raises(AssertionError, match="does not exist: eth0"):
        Network(runner).require_link("eth0")


def test_routes_do_not_hide_unrelated_command_failures() -> None:
    runner = Mock(spec=Runner)
    runner.run.return_value = subprocess.CompletedProcess(
        ["ip"], 1, "[]", "unrelated error"
    )

    with pytest.raises(subprocess.CalledProcessError):
        Network(runner).routes(table=100)


@pytest.mark.parametrize(
    ("topology", "options", "message"),
    (
        ([], {}, "must be a mapping"),
        (_topology(), {"ipv4": False, "ipv6": False}, "IP family"),
        (_topology(), {"ipv4": "true"}, "IP family"),
        (_topology(), {"mtu": 1279}, "MTU"),
        (_topology(), {"timeout": 0}, "timeout"),
        (_topology(), {"prefix": "too-long"}, "five characters"),
        (_topology(), {"prefix": "bad/"}, "invalid interface"),
        ({"physical_bridge": "", "workers": [_worker()]}, {}, "bridge"),
        ({"physical_bridge": "br0", "workers": []}, {}, "one worker"),
        (_topology("worker"), {}, "must be a mapping"),
        (_topology(_worker(), _worker()), {}, "duplicated"),
        (_topology(_worker(chassis="")), {}, "chassis"),
        (_topology(_worker(external_vlan=0)), {}, "VLAN"),
        (_topology(_worker(external={})), {}, "external IPv4"),
        (
            _topology(_worker(external={"ipv4": "2001:db8::/64", "ipv6": "::/64"})),
            {},
            "must be IPv4",
        ),
        (
            _topology(_worker(external={"ipv4": "192.0.2.0/31", "ipv6": "::/64"})),
            {},
            "too small",
        ),
    ),
)
def test_external_peers_reject_invalid_configuration(
    topology: Any, options: dict[str, Any], message: str
) -> None:
    runner = Mock(spec=Runner)

    with pytest.raises(ValueError, match=message):
        ExternalPeers(runner, topology, **options)
    runner.run_many.assert_not_called()


def test_external_peer_names_are_stable_and_commands_are_batched_per_guest() -> None:
    workers = (
        _worker("alpha", "compute-1"),
        _worker("beta", "compute-1"),
        _worker("gamma", "compute-2"),
    )
    runner = Mock(spec=Runner)
    peers = ExternalPeers(runner, _topology(*workers))
    reordered = ExternalPeers(Mock(spec=Runner), _topology(*reversed(workers)))

    assert {name: peer["interface"] for name, peer in peers.peers.items()} == {
        name: peer["interface"] for name, peer in reordered.peers.items()
    }
    assert all(len(peer["interface"]) <= 15 for peer in peers.peers.values())

    peers.create()
    assert runner.run_many.call_count == 2
    compute_one = next(
        call.args[0]
        for call in runner.run_many.call_args_list
        if call.kwargs["guest"] == "compute-1"
    )
    assert (
        len(
            [
                command
                for command, _ in compute_one
                if "netns" in command and "add" in command
            ]
        )
        == 2
    )

    runner.run_many.reset_mock()
    peers.cleanup()
    assert runner.run_many.call_count == 2
    for call in runner.run_many.call_args_list:
        assert all(not check for _, check in call.args[0])
        for command, _ in call.args[0]:
            if "del-port" in command:
                assert "br-provider" not in command


def test_external_peer_cleanup_continues_with_other_guests() -> None:
    runner = Mock(spec=Runner)
    failure = subprocess.CalledProcessError(255, ["ssh"])
    runner.run_many.side_effect = (
        failure,
        subprocess.CompletedProcess(["ssh"], 0, "", ""),
    )
    peers = ExternalPeers(
        runner,
        _topology(
            _worker("alpha", "compute-1"),
            _worker("beta", "compute-2"),
        ),
    )

    with pytest.raises(subprocess.CalledProcessError) as error:
        peers.cleanup()

    assert error.value is failure
    assert runner.run_many.call_count == 2


@pytest.mark.parametrize("remaining", ("namespace", "interface"))
def test_external_peer_cleanup_verification_is_batched(
    remaining: str,
) -> None:
    runner = Mock(spec=Runner)
    peers = ExternalPeers(runner, _topology())
    peer = peers.peers["worker-0"]
    runner.output.side_effect = (
        f"{peer['namespace']} (id: 0)\n" if remaining == "namespace" else "",
        f'"{peer["interface"]}"\n' if remaining == "interface" else "",
    )

    message = "namespace" if remaining == "namespace" else "OVS port"
    with pytest.raises(AssertionError, match=message):
        peers.verify_cleanup()

    assert runner.output.call_count == 2


def test_external_peers_reject_invalid_endpoints() -> None:
    runner = Mock(spec=Runner)
    peers = ExternalPeers(runner, _topology(), ipv6=False)
    invalid_family: Any = 4.0
    invalid: tuple[tuple[Callable[[], object], str], ...] = (
        (lambda: peers.address({}, 4), "worker"),
        (
            lambda: peers.address({"worker": "missing", "guest": "compute-1"}, 4),
            "unknown worker",
        ),
        (
            lambda: peers.address({"worker": "worker-0", "guest": "compute-2"}, 4),
            "different chassis",
        ),
        (
            lambda: peers.verify({"worker": "worker-0", "guest": "compute-1"}),
            "namespace",
        ),
        (
            lambda: peers.verify_inbound(
                {
                    "worker": "worker-0",
                    "guest": "compute-1",
                    "ipv4": "2001:db8::1",
                }
            ),
            "must be IPv4",
        ),
        (
            lambda: peers.address(
                {"worker": "worker-0", "guest": "compute-1"}, invalid_family
            ),
            "family",
        ),
        (
            lambda: peers.address({"worker": "worker-0", "guest": "compute-1"}, 6),
            "disabled",
        ),
    )

    for action, message in invalid:
        with pytest.raises(ValueError, match=message):
            action()
    runner.wait.assert_not_called()


def test_network_observes_namespaces_links_addresses_and_routes(
    topology: Topology,
) -> None:
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

    runner = Runner(topology, execute=execute)
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
            "localized missing table message\n",
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


def test_external_peers_exercise_worker_gateway_paths(fake_runner: Any) -> None:
    runner = fake_runner
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

    peer = peers.peers["worker-0"]
    namespace = peer["namespace"]
    interface = peer["interface"]
    create_guest, create = runner.batches[0]
    assert create_guest == "compute-1"
    commands = [command for command, _ in create]
    assert (
        "ip",
        "-n",
        namespace,
        "address",
        "replace",
        "172.16.0.253/24",
        "dev",
        "eth0",
    ) in commands
    assert (
        "ip",
        "-n",
        namespace,
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
        interface,
        "--",
        "set",
        "Port",
        interface,
        "tag=37",
    ) in commands
    assert [wait[0][-1] for wait in runner.waits] == [
        "172.16.0.253",
        "fd20::ffff:ffff:fffd",
        "10.0.0.1",
        "fd10::1",
    ]
    assert runner.waits[-1][0][3] == namespace

    peers.verify_cleanup()
