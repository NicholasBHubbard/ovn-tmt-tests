import os
import shutil
import stat
from pathlib import Path


def _copy(source, destination):
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


def _collect_artifacts(source, destination):
    destination.mkdir(parents=True, exist_ok=True)
    directories = [path for path in source.rglob("*testsuite.dir") if path.is_dir()]
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
    for artifact in artifacts:
        _copy(artifact, destination / artifact.parent.relative_to(source))

    for path in [destination, *destination.rglob("*")]:
        if path.is_symlink():
            continue
        mode = path.stat().st_mode | stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH
        if path.is_dir():
            mode |= stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
        path.chmod(mode)


def run_make(
    runner,
    source,
    data,
    *,
    target="check",
    testsuiteflags=None,
):
    source = Path(source)
    jobs = len(os.sched_getaffinity(0))
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
