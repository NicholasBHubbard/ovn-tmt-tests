from pathlib import Path

import pytest

from ._support import load_module


def test_southbound_checker_rejects_missing_and_stale_objects(tree: Path) -> None:
    checker = load_module(
        tree,
        "southbound_convergence",
        "roles/ovn_sb_convergence/files/check.py",
    )
    expected = {
        "datapaths": ["present", "missing"],
        "ports": ["present-port"],
        "absent_datapaths": ["stale"],
        "absent_ports": [],
    }

    with pytest.raises(RuntimeError, match=r"missing_datapaths.*stale_datapaths"):
        checker.verify(
            expected,
            {"datapaths": {"present", "stale"}, "ports": {"present-port"}},
        )
