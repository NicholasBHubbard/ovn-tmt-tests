import shlex
from pathlib import Path
from typing import Any, Optional, Union

import yaml


def content(tree: Path, path: Union[str, Path]) -> str:
    return (tree / path).read_text()


def assert_contains(tree: Path, path: Union[str, Path], expected: Any) -> None:
    assert expected in content(tree, path), path


def plan_metadata(
    tree: Path, path: Union[str, Path], node: Optional[str] = None
) -> dict[str, Any]:
    metadata = yaml.safe_load(content(tree, path)) or {}
    return metadata if node is None else metadata[f"/{node}"]


def prepare_phase(
    tree: Path,
    path: Union[str, Path],
    name: Optional[str] = None,
    playbook: Optional[str] = None,
    node: Optional[str] = None,
) -> dict[str, Any]:
    metadata = plan_metadata(tree, path, node)
    phases = []
    for key in ("prepare", "prepare+", "prepare+<"):
        value = metadata.get(key, [])
        phases.extend(value if isinstance(value, list) else [value])
    if name is None and playbook is None:
        assert len(phases) == 1
        return phases[0]
    return next(
        phase
        for phase in phases
        if (name is None or phase.get("name") == name)
        and (playbook is None or phase.get("playbook") == playbook)
    )


def extra_variables(phase: dict[str, Any]) -> dict[str, str]:
    arguments = shlex.split(phase.get("extra-args", ""))
    return {
        assignment.split("=", 1)[0]: assignment.split("=", 1)[1]
        for option, assignment in zip(arguments, arguments[1:])
        if option == "-e" and "=" in assignment
    }
