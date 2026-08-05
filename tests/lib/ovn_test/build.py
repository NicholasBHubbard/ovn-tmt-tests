import os
import shutil
import stat
import subprocess
from pathlib import Path
from typing import Optional, Union

from ovn_test.command import Runner


def _copy(source: Path, destination: Path) -> set[Path]:
    root = destination / source.name
    if root.is_dir() and not root.is_symlink():
        shutil.rmtree(root)
    elif root.exists() or root.is_symlink():
        root.unlink()

    copied = set()
    paths = [source, *source.rglob("*")] if source.is_dir() else [source]
    for path in paths:
        target = destination / path.relative_to(source.parent)
        if path.is_symlink():
            target.parent.mkdir(parents=True, exist_ok=True)
            target.symlink_to(os.readlink(path))
        elif path.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        elif path.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
        else:
            continue
        copied.add(target)
    return copied


def _make_readable(path: Path) -> None:
    mode = path.stat().st_mode | stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH
    if path.is_dir():
        mode |= stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
    path.chmod(mode)


def _collect_artifacts(source: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    directories = [
        path
        for path in source.rglob("*testsuite.dir")
        if path.is_dir() and not path.is_symlink()
    ]
    artifacts = [
        *directories,
        *(
            path
            for path in source.rglob("*testsuite.log")
            if path.is_file()
            and not path.is_symlink()
            and not any(directory in path.parents for directory in directories)
        ),
    ]
    copied = set()
    for artifact in artifacts:
        copied.update(
            _copy(artifact, destination / artifact.parent.relative_to(source))
        )
    published = {destination, *copied}
    for path in copied:
        parent = path.parent
        while parent != destination:
            published.add(parent)
            parent = parent.parent

    for path in published:
        if not path.is_symlink():
            _make_readable(path)


def run_make(
    runner: Runner,
    source: Union[str, os.PathLike[str]],
    data: Union[str, os.PathLike[str]],
    *,
    target: str = "check",
    testsuiteflags: Optional[str] = None,
    jobs: Optional[int] = None,
) -> subprocess.CompletedProcess[str]:
    source = Path(source)
    jobs = len(os.sched_getaffinity(0)) if jobs is None else jobs
    if jobs < 1:
        raise ValueError("jobs must be a positive integer")
    command = ["make", "-j", jobs, target]
    if testsuiteflags:
        command.append(f"TESTSUITEFLAGS={testsuiteflags}")

    result = runner.run(*command, cwd=source, check=False)
    try:
        _collect_artifacts(source, Path(data))
    except Exception:
        if result.returncode:
            result.check_returncode()
        raise
    result.check_returncode()
    return result
