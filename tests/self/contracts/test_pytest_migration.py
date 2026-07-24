from pathlib import Path

import yaml


ROOT = Path(__file__).parents[3]
SELF_TESTS = ROOT / "tests" / "self"
SELF_PLANS = ROOT / "plans" / "self"
PYTEST_SUITES = {
    ROOT / "tests" / "ovn-ci": (
        ["python3-pytest"],
        "ovn_test.pytest_ovn_ci",
    ),
    ROOT / "tests" / "ovn-fake-multinode": (
        ["python3-pytest", "python3-pyyaml"],
        "ovn_test.pytest_multihost",
    ),
}


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


def test_test_metadata_uses_default_framework():
    explicit = [
        path
        for path in (ROOT / "tests").rglob("*.fmf")
        if (yaml.safe_load(path.read_text()) or {}).get("framework") == "shell"
    ]

    assert not explicit


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


def test_multiguest_pytest_dependencies_apply_to_every_guest():
    for suite in ("multihost", "ovn-clustered"):
        base = yaml.safe_load((SELF_PLANS / suite / "main.fmf").read_text())
        packages = {
            package
            for phase in base["prepare"]
            if phase["how"] == "install"
            for package in phase["package"]
        }
        assert packages == {"python3-pytest", "python3-pyyaml"}

        for path in (SELF_PLANS / suite).glob("*.fmf"):
            if path.name == "main.fmf":
                continue
            metadata = yaml.safe_load(path.read_text())
            assert "prepare" not in metadata, path
            assert "prepare+" in metadata, path


def test_self_test_plans_do_not_run_shell_files():
    references = [
        path for path in SELF_PLANS.rglob("*.fmf") if ".sh" in path.read_text()
    ]

    assert not references


def test_repository_has_no_shell_source_files():
    excluded = {
        ".agent-state",
        ".git",
        "SYSTEMS_TO_REPLACE",
        "ovn-tmt-ci-experiment",
    }
    shell = sorted(
        path.relative_to(ROOT)
        for pattern in ("*.sh", "*.bash")
        for path in ROOT.rglob(pattern)
        if not excluded.intersection(path.parts)
    )

    assert not shell


def test_remaining_workloads_run_pytest():
    for suite, (packages, plugin) in PYTEST_SUITES.items():
        base = yaml.safe_load((suite / "main.fmf").read_text())
        assert base["require"] == packages

        for path in suite.glob("*/main.fmf"):
            metadata = yaml.safe_load(path.read_text())
            assert "python3 -m pytest" in metadata["test"], path
            assert f"-p {plugin}" in metadata["test"], path
            assert "framework" not in metadata, path
            assert "require" not in metadata, path
