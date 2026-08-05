import json
import subprocess
import tarfile
from collections.abc import Mapping
from pathlib import Path

import pytest
from ovn_test.command import Runner


def run_playbook(
    tree: Path,
    playbook: str,
    variables: Mapping[str, object],
    *,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    return Runner().run(
        "ansible-playbook",
        "-i",
        "localhost,",
        "-c",
        "local",
        playbook,
        "-e",
        "ansible_become=false",
        "-e",
        json.dumps(variables),
        cwd=tree,
        check=check,
    )


def test_run_diagnostics_preserves_guest_state(tree: Path, tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    output = tmp_path / "output"
    logs = tmp_path / "logs"
    nested_logs = logs / "nested"
    nested_logs.mkdir(parents=True)
    (logs / "ovn.log").write_text("diagnostic marker\n")
    (logs / "nested__ovn.log").write_text("flat path\n")
    (nested_logs / "ovn.log").write_text("nested path\n")
    variables = {
        "run_diagnostics_enabled": "true",
        "run_diagnostics_journal_lines": "100",
        "run_diagnostics_log_bytes": "10485760",
        "run_diagnostics_runtime_dir": str(runtime),
        "run_diagnostics_output_dir": str(output),
        "run_diagnostics_log_directories": [str(logs)],
    }

    run_playbook(tree, "playbooks/run-diagnostics-start.yml", variables)
    run_playbook(tree, "playbooks/run-diagnostics-collect.yml", variables)

    assert not (output / ".localhost.tar.gz.tmp").exists()
    with tarfile.open(output / "localhost.tar.gz") as archive:
        names = archive.getnames()
        assert "collected/system-journal.log" in names
        assert "collected/processes.txt" in names
        assert archive.getmember("collected/processes.txt").mode == 0o600
        archived_logs = {}
        for name in names:
            if not name.endswith(".log.tail"):
                continue
            stream = archive.extractfile(name)
            assert stream is not None
            archived_logs[name] = stream.read()
        assert len(archived_logs) == 3
        assert sorted(archived_logs.values()) == [
            b"diagnostic marker\n",
            b"flat path\n",
            b"nested path\n",
        ]

    (nested_logs / "ovn.log").unlink()
    (logs / "ovn.log").write_text("updated marker\n")
    run_playbook(tree, "playbooks/run-diagnostics-collect.yml", variables)

    with tarfile.open(output / "localhost.tar.gz") as archive:
        log_contents = []
        for name in archive.getnames():
            if not name.endswith(".log.tail"):
                continue
            stream = archive.extractfile(name)
            assert stream is not None
            log_contents.append(stream.read())
        assert sorted(log_contents) == [b"flat path\n", b"updated marker\n"]


@pytest.mark.parametrize(
    "variables",
    (
        {"run_diagnostics_runtime_dir": "relative"},
        {"run_diagnostics_enabled": "yes"},
        {"run_diagnostics_journal_lines": "-1"},
        {"run_diagnostics_log_bytes": "-1"},
        {"run_diagnostics_log_directories": "/var/log"},
        {
            "run_diagnostics_runtime_dir": "/tmp/diagnostics",
            "run_diagnostics_output_dir": "/tmp/diagnostics/collected/output",
        },
    ),
)
def test_run_diagnostics_rejects_unsafe_configuration(
    tree: Path, variables: Mapping[str, object]
) -> None:
    result = run_playbook(
        tree,
        "playbooks/run-diagnostics-start.yml",
        variables,
        check=False,
    )

    assert result.returncode != 0


def test_run_diagnostics_reports_archive_failure(tree: Path, tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    blocked = tmp_path / "not-a-directory"
    blocked.write_text("")

    result = run_playbook(
        tree,
        "playbooks/run-diagnostics-collect.yml",
        {
            "run_diagnostics_runtime_dir": str(runtime),
            "run_diagnostics_output_dir": str(blocked / "output"),
            "run_diagnostics_log_directories": [],
            "run_diagnostics_journal_lines": 1,
        },
    )

    assert result.returncode == 0
    assert "WARNING: Guest diagnostics archive was not created" in result.stdout


def test_run_diagnostics_can_be_disabled_with_invalid_configuration(
    tree: Path,
) -> None:
    run_playbook(
        tree,
        "playbooks/run-diagnostics-start.yml",
        {
            "run_diagnostics_enabled": "false",
            "run_diagnostics_runtime_dir": "relative",
        },
    )
