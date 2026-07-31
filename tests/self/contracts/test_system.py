import subprocess
from typing import Any

import pytest
from ovn_test.command import Runner
from ovn_test.system import ovsdb_control_socket, processes, tcp_listeners
from ovn_test.topology import Topology

from ._support import topology_data


def test_ovsdb_control_socket_uses_process_configuration() -> None:
    output = (
        "10 ovsdb-server --unixctl=/custom/run/ovn/ovnnb_db.ctl nb.db\n"
        "11 ovsdb-server --unixctl=/custom/run/ovn/ovnsb_db.ctl sb.db\n"
    )
    runner = Runner(
        execute=lambda command, **kwargs: subprocess.CompletedProcess(
            command, 0, output, ""
        )
    )

    assert ovsdb_control_socket(runner, "ovnnb_db") == "/custom/run/ovn/ovnnb_db.ctl"
    with pytest.raises(LookupError, match="missing"):
        ovsdb_control_socket(runner, "missing")


def test_system_observes_exact_processes_and_tcp_ports() -> None:
    calls = []

    def execute(command: Any, **kwargs: Any) -> Any:
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


def test_process_observation_distinguishes_absence_from_error() -> None:
    status = 1

    def execute(command: Any, **kwargs: Any) -> Any:
        return subprocess.CompletedProcess(command, status, "", "error")

    runner = Runner(Topology(topology_data()), execute=execute)

    assert processes(runner, "ovn-controller") == []
    status = 2
    with pytest.raises(subprocess.CalledProcessError):
        processes(runner, "ovn-controller")
