import re
import subprocess
from typing import Any
from unittest.mock import Mock

import pytest
from ovn_test.command import Runner
from ovn_test.system import ovsdb_control_socket, processes, tcp_listeners
from ovn_test.topology import Topology


def test_processes_match_a_literal_name() -> None:
    execute = Mock(
        return_value=subprocess.CompletedProcess([], 0, "10 unusual.process\n", "")
    )
    runner = Runner(execute=execute, environment={})

    assert processes(runner, "unusual.process") == ["10 unusual.process"]
    assert execute.call_args.args[0] == [
        "pgrep",
        "-a",
        "-x",
        "--",
        re.escape("unusual.process"),
    ]


def test_processes_distinguish_absence_from_error() -> None:
    execute = Mock(
        side_effect=(
            subprocess.CompletedProcess([], 1, "", ""),
            subprocess.CompletedProcess([], 2, "", "error"),
        )
    )
    runner = Runner(execute=execute, environment={})

    assert processes(runner, "ovn-controller") == []
    with pytest.raises(subprocess.CalledProcessError):
        processes(runner, "ovn-controller")


def test_processes_reject_an_empty_name() -> None:
    execute = Mock()

    with pytest.raises(ValueError, match="process name"):
        processes(Runner(execute=execute), "")

    execute.assert_not_called()


def test_ovsdb_control_socket_handles_raw_process_output() -> None:
    output = (
        '10 ovsdb-server --label=" --unixctl=/custom/run/ovn/ovnnb_db.ctl nb.db\n'
        "11 ovsdb-server --unixctl=/custom/run/ovn/ovnsb_db.ctl sb.db\n"
    )
    runner = Runner(
        execute=Mock(return_value=subprocess.CompletedProcess([], 0, output, "")),
        environment={},
    )

    assert ovsdb_control_socket(runner, "ovnnb_db") == "/custom/run/ovn/ovnnb_db.ctl"


def test_ovsdb_control_socket_rejects_ambiguous_results() -> None:
    output = (
        "10 ovsdb-server --unixctl=/run/one/ovnnb_db.ctl nb.db\n"
        "11 ovsdb-server --unixctl=/run/two/ovnnb_db.ctl nb.db\n"
    )
    runner = Runner(
        execute=Mock(return_value=subprocess.CompletedProcess([], 0, output, "")),
        environment={},
    )

    with pytest.raises(LookupError, match="multiple control sockets"):
        ovsdb_control_socket(runner, "ovnnb_db")


def test_ovsdb_control_socket_reports_guest_when_missing(topology: Topology) -> None:
    execute = Mock(return_value=subprocess.CompletedProcess([], 1, "", ""))
    runner = Runner(topology, execute=execute, environment={})

    with pytest.raises(LookupError, match="ovnnb_db on compute-1"):
        ovsdb_control_socket(runner, "ovnnb_db", guest="compute-1")

    assert execute.call_args.args[0][0] == "ssh"


def test_tcp_listeners_query_the_requested_guest(topology: Topology) -> None:
    output = "LISTEN 0 128 0.0.0.0:6641\n"
    execute = Mock(return_value=subprocess.CompletedProcess([], 0, output, ""))
    runner = Runner(topology, execute=execute, environment={})

    assert tcp_listeners(runner, 6641, guest="compute-1") == [
        "LISTEN 0 128 0.0.0.0:6641"
    ]
    command = execute.call_args.args[0]
    assert command[0] == "ssh"
    assert "ss -H -ltn 'sport = :6641'" in command[-1]


@pytest.mark.parametrize("port", (True, False, 0, -1, 65536, "6641"))
def test_tcp_listeners_reject_invalid_ports(port: Any) -> None:
    execute = Mock()

    with pytest.raises(ValueError, match="TCP port"):
        tcp_listeners(Runner(execute=execute), port)

    execute.assert_not_called()
