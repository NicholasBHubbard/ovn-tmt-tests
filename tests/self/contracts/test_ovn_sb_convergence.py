import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from ._support import load_module


def checker(tree: Path) -> Any:
    return load_module(
        tree,
        "southbound_convergence",
        "roles/ovn_sb_convergence/files/check.py",
    )


def test_southbound_checker_rejects_missing_and_stale_objects(tree: Path) -> None:
    module = checker(tree)
    expected = {
        "datapaths": ["present", "missing"],
        "ports": ["present-port"],
        "absent_datapaths": ["stale"],
        "absent_ports": [],
    }

    with pytest.raises(RuntimeError, match=r"missing_datapaths.*stale_datapaths"):
        module.verify(
            expected,
            {"datapaths": {"present", "stale"}, "ports": {"present-port"}},
        )


def test_southbound_rows_work_on_python_39(
    tree: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = checker(tree)
    output = json.dumps(
        {
            "headings": ["external_ids"],
            "data": [[["map", [["name", "application"]]]]],
        }
    )
    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(stdout=output),
    )

    assert module._rows(["ovn-sbctl"], "Datapath_Binding", "external_ids") == [
        {"external_ids": {"name": "application"}}
    ]


@pytest.mark.parametrize("nested", (False, True))
def test_state_only_overrides_expectations(tree: Path, nested: bool) -> None:
    module = checker(tree)
    config = {
        "datapaths": ["old"],
        "timeout": 120,
        "nbctl": ["ovn-nbctl"],
        "sbctl": ["ovn-sbctl"],
    }
    values = {
        "datapaths": ["new"],
        "started_ns": 123,
        "timeout": 1,
        "nbctl": ["not-ovn-nbctl"],
    }

    merged = module.merge_state(config, {"southbound": values} if nested else values)

    assert merged["datapaths"] == ["new"]
    assert merged["started_ns"] == 123
    assert merged["timeout"] == 120
    assert merged["nbctl"] == ["ovn-nbctl"]


@pytest.mark.parametrize("state", ([], {"southbound": []}))
def test_rejects_invalid_state(tree: Path, state: Any) -> None:
    with pytest.raises(ValueError, match="state"):
        checker(tree).merge_state({}, state)


@pytest.mark.parametrize(
    ("overrides", "message"),
    (
        ({}, "at least one Southbound expectation"),
        ({"datapaths": ["expected"], "nbctl": "ovn-nbctl"}, "command list"),
    ),
)
def test_rejects_invalid_merged_configuration(
    tree: Path, overrides: dict[str, Any], message: str
) -> None:
    config = {
        "datapaths": [],
        "ports": [],
        "absent_datapaths": [],
        "absent_ports": [],
        "timeout": 120,
        "nbctl": ["ovn-nbctl"],
        "sbctl": ["ovn-sbctl"],
        **overrides,
    }

    with pytest.raises(ValueError, match=message):
        checker(tree).check(config)
