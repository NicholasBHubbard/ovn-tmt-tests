import subprocess
from collections.abc import Callable
from typing import Any
from unittest.mock import Mock

import pytest
from ovn_test.command import Runner
from ovn_test.network import ExternalPeers, Network


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
