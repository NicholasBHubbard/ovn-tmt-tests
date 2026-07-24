import stat
import subprocess

import pytest

import ovn_test.build
from ovn_test.build import run_make
from ovn_test.command import Runner


def test_run_make_preserves_failure_and_artifacts(tmp_path):
    source = tmp_path / "source"
    data = tmp_path / "data"
    source.mkdir()
    data.mkdir()
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
    for path in data.rglob("*"):
        if path.is_symlink():
            continue
        mode = path.stat().st_mode
        if path.is_dir():
            assert mode & stat.S_IROTH and mode & stat.S_IXOTH
        else:
            assert mode & stat.S_IROTH


def test_run_make_uses_requested_target(tmp_path):
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

    run_make(Runner(), source, data, target="distcheck")

    assert (source / "ovn-fixture.tar.gz").is_file()


def test_make_failure_wins_over_artifact_copy_failure(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    (source / "Makefile").write_text("check:\n\tfalse\n")

    def fail_copy(*_):
        raise PermissionError("cannot copy artifacts")

    monkeypatch.setattr(ovn_test.build, "_collect_artifacts", fail_copy)

    with pytest.raises(subprocess.CalledProcessError) as error:
        run_make(Runner(), source, tmp_path / "data")

    assert error.value.returncode == 2
