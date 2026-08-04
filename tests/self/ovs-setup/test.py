import shutil
from pathlib import Path

from ovn_test.command import Runner
from ovn_test.ovsdb import Ovsdb
from ovn_test.state import Snapshots
from ovn_test.system import processes


class TestPreconditions:
    def test_ovs_is_not_configured(self) -> None:
        runner = Runner()

        assert not runner.succeeds("ovs-vsctl", "show")
        assert not processes(runner, "ovs-vswitchd")
        assert not processes(runner, "ovsdb-server")


class TestInitial:
    def test_bridges(self, snapshots: Snapshots) -> None:
        runner = Runner()
        ovs = Ovsdb(runner, "ovs-vsctl")

        assert runner.succeeds("ovs-vsctl", "br-exists", "self-br-keep")
        assert runner.succeeds("ovs-vsctl", "br-exists", "self-br-delete")
        snapshots.save(
            "ovs-bridge",
            ovs.by_name(
                "Bridge",
                "self-br-keep",
                "_uuid",
            )["_uuid"],
        )


class TestReconfigured:
    def test_bridge_identity_is_recorded(self, snapshots: Snapshots) -> None:
        ovs = Ovsdb(Runner(), "ovs-vsctl")

        snapshots.save(
            "ovs-bridge-reconfigured",
            ovs.by_name(
                "Bridge",
                "self-br-keep",
                "_uuid",
            )["_uuid"],
        )


class TestResult:
    def test_git_refspec_is_configured(self, tree: Path) -> None:
        tasks = (tree / "roles/ovs_setup/tasks/git.yml").read_text()

        assert (
            'refspec: "+{{ ovs_setup_git_version }}:refs/ovs-tmt/'
            '{{ ovs_setup_git_version }}"'
        ) in tasks

    def test_ovs_is_running(self) -> None:
        runner = Runner()

        assert runner.succeeds("ovs-vsctl", "show")
        assert shutil.which("ovs-vswitchd")
        assert shutil.which("ovsdb-server")
        assert processes(runner, "ovsdb-server")
        assert processes(runner, "ovs-vswitchd")

    def test_reusable_ovs_state(self, snapshots: Snapshots) -> None:
        runner = Runner()
        ovs = Ovsdb(runner, "ovs-vsctl")
        bridge_uuid = ovs.by_name(
            "Bridge",
            "self-br-keep",
            "_uuid",
        )["_uuid"]

        assert bridge_uuid == snapshots.load("ovs-bridge")
        assert bridge_uuid == snapshots.load("ovs-bridge-reconfigured")
        assert runner.succeeds("ovs-vsctl", "br-exists", "self-br-keep")
        assert not runner.succeeds("ovs-vsctl", "br-exists", "self-br-delete")
        assert runner.succeeds("ovs-vsctl", "br-exists", "self-bridge-new")
