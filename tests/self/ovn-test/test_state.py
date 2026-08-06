from pathlib import Path

import pytest
from ovn_test.state import Snapshots


def test_snapshots_preserve_values(tmp_path: Path) -> None:
    snapshots = Snapshots(tmp_path)

    assert snapshots.save("port-id", 123) == "123"
    assert snapshots.load("port-id") == "123"
    assert snapshots.path("port-id") == tmp_path / "port-id"


@pytest.mark.parametrize("name", ("", ".", "..", "nested/name", "/absolute"))
def test_snapshots_reject_invalid_names(tmp_path: Path, name: str) -> None:
    snapshots = Snapshots(tmp_path / "snapshots")

    with pytest.raises(ValueError, match="single path component"):
        snapshots.save(name, "bad")

    assert not snapshots.root.exists()


def test_snapshots_use_tmt_test_data(tmp_path: Path) -> None:
    snapshots = Snapshots.from_environment({"TMT_TEST_DATA": str(tmp_path)})

    snapshots.save("switch-id", "uuid-2")

    assert (tmp_path / "snapshots" / "switch-id").read_text() == "uuid-2"


def test_snapshots_use_process_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("TMT_PLAN_DATA", raising=False)
    monkeypatch.setenv("TMT_TEST_DATA", str(tmp_path))

    assert Snapshots.from_environment().root == tmp_path / "snapshots"


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


def test_snapshots_fall_back_from_blank_plan_data(tmp_path: Path) -> None:
    snapshots = Snapshots.from_environment(
        {"TMT_PLAN_DATA": "", "TMT_TEST_DATA": str(tmp_path)}
    )

    assert snapshots.root == tmp_path / "snapshots"


def test_snapshots_accept_tmt_plan_data_without_test_data(tmp_path: Path) -> None:
    snapshots = Snapshots.from_environment({"TMT_PLAN_DATA": str(tmp_path)})

    snapshots.save("switch-id", "uuid-4")

    assert (tmp_path / "snapshots" / "switch-id").read_text() == "uuid-4"


@pytest.mark.parametrize(
    "environment",
    (
        {},
        {"TMT_PLAN_DATA": ""},
        {"TMT_TEST_DATA": ""},
        {"TMT_PLAN_DATA": "", "TMT_TEST_DATA": ""},
    ),
)
def test_snapshots_require_a_data_directory(environment: dict[str, str]) -> None:
    with pytest.raises(ValueError, match="TMT_PLAN_DATA or TMT_TEST_DATA must be set"):
        Snapshots.from_environment(environment)
