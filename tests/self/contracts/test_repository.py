import subprocess
from pathlib import Path

import pytest
import yaml
from ovn_test.command import Runner
from ovn_test.files import find_text

from ._metadata import content, plan_metadata

INHERITED_SELF_PLANS = (
    "brew-packages",
    "ci",
    "dpdk-build",
    "kube-burner",
    "multihost",
    "ovn-central",
    "ovn-central-ssl",
    "ovn-clustered",
    "ovn-endpoints",
    "ovn-chassis",
    "ovn-install",
    "ovn-sb-convergence",
    "ovn-scale-topology",
    "ovn-system-test-deps",
    "ovn-topology",
    "ovn-unit-test-deps",
    "ovs-endpoints",
    "ovs-external-ids",
    "ovs-setup",
)


def run_naming(tree: Path, root: Path) -> subprocess.CompletedProcess[str]:
    return Runner().run(
        "python3",
        tree / "tools/check-naming.py",
        root,
        check=False,
    )


class TestPreconditions:
    def test_self_test_directory_exists(self, tree: Path) -> None:
        assert (tree / "tests/self").is_dir()


class TestNaming:
    def test_valid_names(self, tree: Path, tmp_path: Path) -> None:
        defaults = tmp_path / "roles/example/defaults"
        plans = tmp_path / "plans"
        defaults.mkdir(parents=True)
        plans.mkdir()
        (defaults / "main.yaml").write_text("example: []\n")
        (plans / "main.fmf").write_text("environment:\n  OTT_EXAMPLE: value\n")

        assert run_naming(tree, tmp_path).returncode == 0

    def test_invalid_role_variable(self, tree: Path, tmp_path: Path) -> None:
        defaults = tmp_path / "roles/example/defaults"
        defaults.mkdir(parents=True)
        (tmp_path / "plans").mkdir()
        (defaults / "main.yaml").write_text("wrong_name: true\n")

        assert run_naming(tree, tmp_path).returncode != 0

    def test_invalid_environment_variable(self, tree: Path, tmp_path: Path) -> None:
        defaults = tmp_path / "roles/example/defaults"
        plans = tmp_path / "plans"
        defaults.mkdir(parents=True)
        plans.mkdir()
        (defaults / "main.yaml").write_text("example: []\n")
        (plans / "main.fmf").write_text("environment:\n  WRONG_NAME: value\n")

        assert run_naming(tree, tmp_path).returncode != 0

    def test_missing_root(self, tree: Path, tmp_path: Path) -> None:
        assert run_naming(tree, tmp_path / "missing").returncode != 0

    def test_repository_names(self, tree: Path) -> None:
        assert run_naming(tree, tree).returncode == 0


def test_every_self_test_is_referenced_by_a_plan(tree: Path) -> None:
    plans = tree / "plans/self"
    for test_dir in (tree / "tests/self").iterdir():
        if not test_dir.is_dir() or test_dir.name.startswith((".", "__")):
            continue
        assert (test_dir / "main.fmf").is_file()
        assert list(test_dir.glob("test*.py"))
        assert find_text(plans, f"/tests/self/{test_dir.name}")


def test_role_readmes_follow_common_structure(tree: Path) -> None:
    readmes = sorted((tree / "roles").glob("*/README.md"))
    assert readmes
    for readme in readmes:
        text = readme.read_text()
        assert text.startswith(f"# {readme.parent.name}\n")
        assert "playbooks/" not in text
        sections = [
            text.index(f"## {name}")
            for name in (
                "Purpose",
                "Configuration",
                "Usage",
            )
        ]
        assert sections == sorted(sections)


def test_pytest_prepare_phases_run_after_test_dependencies(tree: Path) -> None:
    for path in (tree / "plans/self").rglob("*.fmf"):
        prepare = (yaml.safe_load(path.read_text()) or {}).get("prepare", [])
        previous = None
        for phase in prepare:
            if "python3 -m pytest" in phase.get("script", ""):
                assert phase.get("order", 50) > 70, path
                previous = phase["order"]
            elif previous is not None:
                assert phase.get("order", 50) > previous, path
                previous = phase["order"]


@pytest.mark.parametrize("plan_dir", INHERITED_SELF_PLANS)
def test_self_test_children_inherit_common_steps(tree: Path, plan_dir: Path) -> None:
    directory = tree / "plans/self" / plan_dir
    parent = directory / "main.fmf"
    assert parent.is_file()
    for plan in directory.glob("*.fmf"):
        if plan == parent:
            continue
        text = plan.read_text()
        assert "\nexecute:" not in f"\n{text}"
        if plan_dir not in {"multihost", "ovn-clustered"}:
            assert "\ndiscover:" not in f"\n{text}"


def test_disabled_self_test_parents_use_main_metadata(tree: Path) -> None:
    for path in (tree / "plans/self").rglob("base.fmf"):
        assert "\nenabled: false\n" not in f"\n{path.read_text()}\n"


def test_sb_convergence_has_a_focused_self_test(tree: Path) -> None:
    family = "ovn-sb-convergence"
    role_reference = "role: ovn_sb_convergence"
    assert find_text(tree / "tests/self" / family, role_reference)
    assert find_text(tree / "plans/self" / family, f"/tests/self/{family}")

    generic = tree / "tests/self/ovn-topology"
    assert not find_text(generic, role_reference)


def test_ovn_ci_children_inherit_execution(tree: Path) -> None:
    directory = tree / "plans/ovn-ci"
    for plan in directory.glob("*.fmf"):
        if plan.name != "main.fmf":
            assert "\nexecute:" not in f"\n{plan.read_text()}"


def test_multihost_children_inherit_base(tree: Path) -> None:
    for family in ("ovn-fake-multinode", "ovn-scale-testing"):
        for plan in (tree / "plans" / family).rglob("*.fmf"):
            if plan.name == "main.fmf":
                continue
            assert "playbook: playbooks/multihost.yml" not in plan.read_text()
            assert "enabled: true" in plan.read_text()


def test_top_level_plan_inheritance_is_explicit(tree: Path) -> None:
    plans = tree / "plans"
    shared = {"ovn-fake-multinode", "ovn-scale-testing"}
    assert {path.name for path in plans.iterdir() if path.is_dir()} >= shared

    root = plan_metadata(tree, "plans/main.fmf")
    assert root["/"] == {"inherit": False}
    assert {key.removeprefix("/") for key in root if key != "/"} == shared

    fake = root["/ovn-fake-multinode"]
    scale = root["/ovn-scale-testing"]
    assert fake["environment"].items() <= scale["environment"].items()
    scale_prepare = [
        phase
        for phase in scale["prepare"]
        if phase["name"] != "Install scale workload dependencies"
    ]
    assert len(fake["prepare"]) == len(scale_prepare)
    assert all(
        fake_phase is scale_phase
        for fake_phase, scale_phase in zip(fake["prepare"], scale_prepare)
    )
    assert fake["execute"] is scale["execute"]
    assert fake["finish"] is scale["finish"]
    assert "<<: *multihost_plan" in content(tree, "plans/main.fmf")
    assert "<<: *multihost_environment" in content(tree, "plans/main.fmf")
    assert "discover" not in fake
    assert "discover" not in scale

    for family in (path for path in plans.iterdir() if path.is_dir()):
        parent = family / "main.fmf"
        if family.name in shared:
            assert not parent.exists()
            continue
        assert parent.is_file(), family
        metadata = yaml.safe_load(parent.read_text()) or {}
        assert metadata.get("/", {}).get("inherit") is False, family


def test_multihost_setup_is_test_scoped(tree: Path) -> None:
    plans = "\n".join(
        path.read_text() for path in (tree / "plans/ovn-fake-multinode").rglob("*.fmf")
    )
    for setup in (tree / "tests/ovn-fake-multinode").glob("*/setup.yml"):
        if setup.parent.name == "gateway-nat":
            continue
        test = setup.with_name("test.py")
        assert test.is_file()
        assert 'pytest.mark.usefixtures("setup_scenario")' in test.read_text()
        assert str(setup).removeprefix(f"{tree}/") not in plans
