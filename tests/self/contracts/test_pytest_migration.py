from pathlib import Path

import yaml


ROOT = Path(__file__).parents[3]
SELF_TESTS = ROOT / "tests" / "self"
SELF_PLANS = ROOT / "plans" / "self"


def test_every_self_test_has_python_tests():
    missing = [
        path
        for path in SELF_TESTS.iterdir()
        if path.is_dir()
        and not path.name.startswith((".", "__"))
        and not list(path.glob("test*.py"))
    ]

    assert not missing


def test_self_tests_have_no_shell_files():
    assert not list(SELF_TESTS.rglob("*.sh"))


def test_self_test_metadata_runs_pytest():
    metadata = list(SELF_TESTS.glob("*/main.fmf"))

    assert metadata
    for path in metadata:
        assert "python3 -m pytest" in path.read_text(), path


def test_self_test_python_dependencies_support_rpm_and_deb():
    metadata = yaml.safe_load((SELF_TESTS / "main.fmf").read_text())

    assert metadata["require"] == ["python3-pytest"]
    assert metadata["recommend"] == ["python3-pyyaml", "python3-yaml"]


def test_self_test_suite_dependencies_extend_parent():
    replacements = [
        path
        for path in SELF_TESTS.glob("*/main.fmf")
        if "require" in yaml.safe_load(path.read_text())
    ]

    assert not replacements


def test_self_test_plans_do_not_run_shell_files():
    references = [
        path for path in SELF_PLANS.rglob("*.fmf") if ".sh" in path.read_text()
    ]

    assert not references
