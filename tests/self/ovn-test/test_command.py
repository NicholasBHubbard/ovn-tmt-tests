import json
import os
import shlex
import subprocess
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any, NoReturn

import pytest
from ovn_test.command import Runner
from ovn_test.topology import Topology


def test_runner_conveniences(
    capsys: pytest.CaptureFixture[str], topology: Topology
) -> None:
    calls = []
    responses = iter(
        [
            subprocess.CompletedProcess([], 0, " value \n", ""),
            subprocess.CompletedProcess([], 0, "raw\n", ""),
            subprocess.CompletedProcess([], 0, "", ""),
        ]
    )

    def execute(command: Any, **kwargs: Any) -> Any:
        calls.append((command, kwargs))
        return next(responses)

    runner = Runner(topology, execute=execute, environment={})

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
    assert calls[0][1]["env"]["EXAMPLE"] == "value"
    assert calls[0][1]["env"]["PATH"] == os.environ["PATH"]
    assert "+ ip netns exec sandbox ip link show" in capsys.readouterr().out


def test_runner_reports_command_success(topology: Topology) -> None:
    runner = Runner(
        topology,
        execute=lambda command, **kwargs: subprocess.CompletedProcess(
            command, int(command == ["false"]), "", ""
        ),
        environment={},
    )

    assert runner.succeeds("true")
    assert not runner.succeeds("false")


def test_runner_reports_missing_commands_as_unsuccessful() -> None:
    def execute(command: Any, **kwargs: Any) -> NoReturn:
        raise FileNotFoundError(command[0])

    assert not Runner(execute=execute).succeeds("missing")


def test_runner_does_not_require_topology_for_local_commands() -> None:
    runner = Runner(
        execute=lambda command, **kwargs: subprocess.CompletedProcess(
            command, 0, "local\n", ""
        )
    )

    assert runner.output("hostname") == "local"
    with pytest.raises(ValueError, match="topology"):
        runner.run("hostname", guest="compute-1")


def test_runner_normalizes_arguments_and_wait_options() -> None:
    calls = []

    def execute(command: Any, **kwargs: Any) -> Any:
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
    assert calls[1][1]["env"]["EXAMPLE"] == "value"
    assert calls[1][1]["env"]["PATH"] == os.environ["PATH"]


def test_runner_serializes_remote_command_batches(
    capsys: pytest.CaptureFixture[str],
    topology: Topology,
) -> None:
    calls = []

    def execute(command: Any, **kwargs: Any) -> Any:
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, "", "")

    Runner(topology, execute=execute, environment={}).run_many(
        [
            (["true", 1], True),
            (["false"], False),
        ],
        guest="compute-1",
    )

    assert calls[0][0][-1].startswith("python3 -c ")
    assert json.loads(calls[0][1]["input"]) == [
        [["true", "1"], True],
        [["false"], False],
    ]
    output = capsys.readouterr().out
    assert output.splitlines() == [
        "compute-1: command batch started",
        "compute-1: command batch completed successfully",
    ]


def test_runner_command_batches_honor_error_handling(
    capsys: pytest.CaptureFixture[str],
) -> None:
    python = sys.executable
    result = Runner().run_many(
        [
            ([python, "-c", "raise SystemExit(1)"], False),
            ([python, "-c", "print('continued')"], True),
        ]
    )

    assert "continued" in result.stdout
    output = capsys.readouterr().out
    assert "local: command batch started" in output
    assert f"local: + {python} -c 'raise SystemExit(1)'  [nonfatal 1]" in output
    assert "[nonfatal 0]" not in output
    assert "local: command batch completed successfully" in output

    with pytest.raises(subprocess.CalledProcessError) as error:
        Runner().run_many([([python, "-c", "raise SystemExit(7)"], True)])
    output = capsys.readouterr().out
    assert error.value.returncode == 7
    assert "Traceback" not in output
    assert "local: command batch failed (exit status 7)" in output


def test_runner_command_batches_keep_errors_with_commands(
    capsys: pytest.CaptureFixture[str],
) -> None:
    python = sys.executable
    Runner().run_many(
        [
            (
                [
                    python,
                    "-c",
                    "import sys; sys.stderr.write('batch-' + 'error\\n'); "
                    "raise SystemExit(1)",
                ],
                False,
            ),
            ([python, "-c", "pass"], True),
        ]
    )

    output = capsys.readouterr().out
    marker = output.index("[nonfatal 1]")
    error = output.index("batch-error")
    next_command = output.index(f"local: + {python} -c pass")
    assert marker < error < next_command


def test_runner_waits_for_a_result(topology: Topology) -> None:
    results = iter(
        [
            subprocess.CompletedProcess([], 1, "", "not yet\n"),
            subprocess.CompletedProcess([], 0, "", ""),
            subprocess.CompletedProcess([], 0, "ready\n", ""),
        ]
    )
    sleeps = []

    runner = Runner(
        topology,
        execute=lambda command, **kwargs: next(results),
        sleep=sleeps.append,
        environment={},
    )

    result = runner.wait(
        "probe",
        attempts=3,
        interval=0.25,
        until=lambda completed: completed.stdout.strip() == "ready",
    )

    assert result.stdout == "ready\n"
    assert sleeps == [0.25, 0.25]


def test_runner_wait_reports_timeout(topology: Topology) -> None:
    calls = 0

    def execute(command: Any, **kwargs: Any) -> Any:
        nonlocal calls
        calls += 1
        return subprocess.CompletedProcess(command, 1, "", "still unavailable\n")

    runner = Runner(
        topology,
        execute=execute,
        sleep=lambda interval: None,
        environment={},
    )

    with pytest.raises(TimeoutError, match=r"probe.*3 attempts"):
        runner.wait("probe", attempts=3, interval=0)
    assert calls == 3

    with pytest.raises(ValueError, match="attempts"):
        runner.wait("probe", attempts=0)


def test_runner_executes_locally_and_over_ssh(
    capsys: pytest.CaptureFixture[str],
    topology: Topology,
) -> None:
    calls = []

    def execute(command: Any, **kwargs: Any) -> Any:
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, "ok\n", "")

    runner = Runner(topology, execute=execute, environment={})

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
        "-o",
        "IdentitiesOnly=yes",
        "root@192.0.2.2",
        "ip link show",
    ]
    assert calls[1][1]["input"] == "stdin"
    assert "+ ovn-nbctl show" in capsys.readouterr().out


def test_runner_applies_working_directory_and_environment_remotely(
    topology: Topology,
) -> None:
    calls = []

    def execute(command: Any, **kwargs: Any) -> Any:
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, "", "")

    Runner(topology, execute=execute, environment={}).run(
        "printenv",
        "EXAMPLE",
        guest="compute-1",
        cwd="/remote work",
        env={"EXAMPLE": "some value"},
    )

    assert calls[0][0][-1] == (
        "cd '/remote work' && env 'EXAMPLE=some value' printenv EXAMPLE"
    )
    assert calls[0][1]["cwd"] is None
    assert calls[0][1]["env"] is None


def test_runner_uses_configured_driver_connection(topology: Topology) -> None:
    calls = []

    def execute(command: Any, **kwargs: Any) -> Any:
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, "", "")

    runner = Runner(
        topology,
        execute=execute,
        environment={
            "OTT_DRIVER_CONNECT_TIMEOUT": "45",
            "OTT_DRIVER_USER": "tester",
            "OTT_DRIVER_RUNTIME_DIR": "/custom/driver",
        },
    )
    runner.run("true", guest="compute-1")

    assert calls[0][calls[0].index("-i") + 1] == "/custom/driver/id_ed25519"
    assert "ConnectTimeout=45" in calls[0]
    assert "IdentitiesOnly=yes" in calls[0]
    assert "tester@192.0.2.2" in calls[0]


@pytest.mark.parametrize("ssl", (False, True))
def test_runner_uses_cluster_database_remotes(ssl: bool, topology: Topology) -> None:
    calls = []
    data = deepcopy(topology.data)
    data["guests"]["central-2"] = {
        "name": "central-2",
        "hostname": "198.51.100.2",
        "role": "central-follower",
    }
    data["roles"]["central-follower"] = ["central-2"]
    environment = {
        "OTT_CLUSTERED": "true",
        "OTT_NB_PORT": "16641",
        "OTT_SB_PORT": "16642",
        "OTT_SSL_ENABLED": str(ssl).lower(),
        "OTT_PKI_REMOTE_DIR": "/custom/pki",
    }

    runner = Runner(
        Topology(data),
        execute=lambda command, **kwargs: (
            calls.append((command, kwargs))
            or subprocess.CompletedProcess(command, 0, "", "")
        ),
        environment=environment,
    )
    runner.run("ovn-nbctl", "show")
    runner.run("ovn-nbctl", "show", guest="compute-1")

    command_environment = calls[0][1]["env"]
    protocol = "ssl" if ssl else "tcp"
    assert command_environment["OVN_NB_DB"] == (
        f"{protocol}:192.0.2.1:16641,{protocol}:198.51.100.2:16641"
    )
    assert command_environment["OVN_SB_DB"] == (
        f"{protocol}:192.0.2.1:16642,{protocol}:198.51.100.2:16642"
    )
    if ssl:
        for name in ("OVN_NBCTL_OPTIONS", "OVN_SBCTL_OPTIONS"):
            assert command_environment[name] == (
                "--private-key=/custom/pki/private-key.pem "
                "--certificate=/custom/pki/certificate.pem "
                "--ca-cert=/custom/pki/ca-cert.pem"
            )
    else:
        assert "OVN_NBCTL_OPTIONS" not in command_environment
        assert "OVN_SBCTL_OPTIONS" not in command_environment

    remote_arguments = shlex.split(calls[1][0][-1])
    assert remote_arguments[0] == "env"
    for name, value in runner.database_environment.items():
        assert f"{name}={value}" in remote_arguments
    assert remote_arguments[-2:] == ["ovn-nbctl", "show"]
    assert calls[1][1]["env"] is None
