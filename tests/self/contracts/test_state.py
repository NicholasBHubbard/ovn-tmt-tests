from pathlib import Path

import pytest
from ovn_test.state import Snapshots


def test_snapshots_preserve_values(tmp_path: Path) -> None:
    snapshots = Snapshots(tmp_path)

    assert snapshots.save("port-id", "uuid-1") == "uuid-1"
    assert snapshots.load("port-id") == "uuid-1"
    assert snapshots.path("port-id") == tmp_path / "port-id"

    with pytest.raises(ValueError, match="snapshot name"):
        snapshots.save("../outside", "bad")


def test_snapshots_use_tmt_test_data(tmp_path: Path) -> None:
    snapshots = Snapshots.from_environment({"TMT_TEST_DATA": str(tmp_path)})

    snapshots.save("switch-id", "uuid-2")

    assert (tmp_path / "snapshots" / "switch-id").read_text() == "uuid-2"


def test_snapshots_prefer_stable_tmt_plan_data(tmp_path: Path) -> None:
    plan_data = tmp_path / "plan"
    test_data = tmp_path / "test"
    snapshots = Snapshots.from_environment(
        {
            "TMT_PLAN_DATA": str(plan_data),
            "TMT_TEST_DATA": str(test_data),
        }
    )

    snapshots.save("switch-id", "uuid-3")

    assert (plan_data / "snapshots" / "switch-id").read_text() == "uuid-3"
    assert not test_data.exists()


def test_snapshots_accept_tmt_plan_data_without_test_data(tmp_path: Path) -> None:
    snapshots = Snapshots.from_environment({"TMT_PLAN_DATA": str(tmp_path)})

    snapshots.save("switch-id", "uuid-4")

    assert (tmp_path / "snapshots" / "switch-id").read_text() == "uuid-4"
