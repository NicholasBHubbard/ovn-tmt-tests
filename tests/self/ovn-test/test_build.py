import stat
import subprocess
from pathlib import Path
from typing import Any, NoReturn

import ovn_test.build
import pytest
from ovn_test.build import _collect_artifacts, run_make
from ovn_test.command import Runner


def test_run_make_preserves_failure_and_artifacts(tmp_path: Path) -> None:
    source = tmp_path / "source"
    data = tmp_path / "data"
    source.mkdir()
    data.mkdir()
    unrelated = data / "unrelated"
    unrelated.write_text("not a build artifact")
    unrelated.chmod(0o600)
    (source / "Makefile").write_text(
        """\
check:
\ttest "$(TESTSUITEFLAGS)" = "7-9"
\tmkdir -p tests/failed-testsuite.dir
\ttouch tests/failed-testsuite.log
\ttouch tests/failed-testsuite.dir/details.log
\tln -s missing tests/failed-testsuite.dir/dangling
\tmkfifo tests/failed-testsuite.dir/socket
\tchmod 700 tests/failed-testsuite.dir
\tchmod 600 tests/failed-testsuite.log tests/failed-testsuite.dir/details.log
\tfalse
"""
    )

    with pytest.raises(subprocess.CalledProcessError) as error:
        run_make(
            Runner(),
            source,
            data,
            testsuiteflags="7-9",
        )

    assert error.value.returncode == 2
    assert (data / "tests/failed-testsuite.log").is_file()
    assert (data / "tests/failed-testsuite.dir/details.log").is_file()
    assert (data / "tests/failed-testsuite.dir/dangling").is_symlink()
    assert not (data / "tests/failed-testsuite.dir/socket").exists()
    for path in (data / "tests").rglob("*"):
        if path.is_symlink():
            continue
        mode = path.stat().st_mode
        if path.is_dir():
            assert mode & stat.S_IROTH
            assert mode & stat.S_IXOTH
        else:
            assert mode & stat.S_IROTH
    assert stat.S_IMODE(unrelated.stat().st_mode) == 0o600


def test_run_make_uses_requested_target(tmp_path: Path) -> None:
    source = tmp_path / "source"
    data = tmp_path / "data"
    source.mkdir()
    data.mkdir()
    (source / "Makefile").write_text(
        """\
distcheck:
\ttouch ovn-fixture.tar.gz
"""
    )

    run_make(Runner(), source, data, target="distcheck", jobs=1)

    assert (source / "ovn-fixture.tar.gz").is_file()


def test_run_make_uses_affinity_by_default_and_accepts_explicit_jobs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    commands = []

    def execute(command: list[str], **_: Any) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(ovn_test.build.os, "sched_getaffinity", lambda _: {0, 1, 2})
    runner = Runner(execute=execute)

    run_make(runner, tmp_path, tmp_path / "default")
    run_make(
        runner,
        tmp_path,
        tmp_path / "explicit",
        target="distcheck",
        testsuiteflags="4-6",
        jobs=2,
    )

    assert commands == [
        ["make", "-j", "3", "check"],
        ["make", "-j", "2", "distcheck", "TESTSUITEFLAGS=4-6"],
    ]


@pytest.mark.parametrize("jobs", (0, -1))
def test_run_make_rejects_invalid_jobs(tmp_path: Path, jobs: int) -> None:
    with pytest.raises(ValueError, match="jobs must be a positive integer"):
        run_make(Runner(), tmp_path, tmp_path / "data", jobs=jobs)


def test_artifact_collection_replaces_previous_copy(tmp_path: Path) -> None:
    source = tmp_path / "source"
    suite = source / "tests/testsuite.dir"
    data = tmp_path / "data"
    suite.mkdir(parents=True)
    old = suite / "old.log"
    link = suite / "latest"
    old.write_text("old")
    link.symlink_to("old.log")

    _collect_artifacts(source, data)

    old.unlink()
    link.unlink()
    (suite / "new.log").write_text("new")
    link.symlink_to("new.log")
    _collect_artifacts(source, data)

    collected = data / "tests/testsuite.dir"
    assert not (collected / "old.log").exists()
    assert (collected / "new.log").read_text() == "new"
    assert (collected / "latest").readlink() == Path("new.log")


def test_make_failure_wins_over_artifact_copy_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "Makefile").write_text("check:\n\tfalse\n")

    def fail_copy(*_: Any) -> NoReturn:
        raise PermissionError("cannot copy artifacts")

    monkeypatch.setattr(ovn_test.build, "_collect_artifacts", fail_copy)

    with pytest.raises(subprocess.CalledProcessError) as error:
        run_make(Runner(), source, tmp_path / "data")

    assert error.value.returncode == 2


def test_artifact_copy_failure_is_reported_after_make_succeeds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "Makefile").write_text("check:\n\ttrue\n")

    def fail_copy(*_: Any) -> NoReturn:
        raise PermissionError("cannot copy artifacts")

    monkeypatch.setattr(ovn_test.build, "_collect_artifacts", fail_copy)

    with pytest.raises(PermissionError, match="cannot copy artifacts"):
        run_make(Runner(), source, tmp_path / "data", jobs=1)
