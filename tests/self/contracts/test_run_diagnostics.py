import json
import tarfile
from collections.abc import Mapping
from pathlib import Path

from ovn_test.command import Runner


def run_playbook(tree: Path, playbook: str, variables: Mapping[str, object]) -> None:
    Runner().run(
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
    )


def test_run_diagnostics_preserves_guest_state(tree: Path, tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    output = tmp_path / "output"
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "ovn.log").write_text("diagnostic marker\n")
    variables = {
        "run_diagnostics_runtime_dir": str(runtime),
        "run_diagnostics_output_dir": str(output),
        "run_diagnostics_log_directories": [str(logs)],
    }

    run_playbook(tree, "playbooks/run-diagnostics-start.yml", variables)
    run_playbook(tree, "playbooks/run-diagnostics-collect.yml", variables)

    with tarfile.open(output / "localhost.tar.gz") as archive:
        names = archive.getnames()
        assert "collected/system-journal.log" in names
        assert "collected/processes.txt" in names
        log = next(name for name in names if name.endswith("ovn.log.tail"))
        stream = archive.extractfile(log)
        assert stream is not None
        assert stream.read() == b"diagnostic marker\n"
