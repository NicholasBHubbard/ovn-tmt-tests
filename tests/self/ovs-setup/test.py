import shutil

from ovn_test.command import Runner
from ovn_test.ovsdb import Ovsdb
from ovn_test.system import processes


class TestPreconditions:
    def test_ovs_is_not_configured(self):
        runner = Runner()

        assert not runner.succeeds("ovs-vsctl", "show")
        assert not processes(runner, "ovs-vswitchd")
        assert not processes(runner, "ovsdb-server")


def external_id(runner, name):
    return runner.output(
        "ovs-vsctl",
        "--if-exists",
        "get",
        "Open_vSwitch",
        ".",
        f"external_ids:{name}",
    ).strip('"')


class TestInitial:
    def test_bridges_and_external_ids(self, snapshots):
        runner = Runner()
        ovs = Ovsdb(runner, "ovs-vsctl")

        assert runner.succeeds("ovs-vsctl", "br-exists", "self-bridge-keep")
        assert runner.succeeds("ovs-vsctl", "br-exists", "self-bridge-delete")
        assert external_id(runner, "self-managed") == "initial"
        assert external_id(runner, "self-delete") == "remove-me"
        assert external_id(runner, "self-unmanaged") == "preserve"
        snapshots.save(
            "ovs-bridge",
            ovs.one(
                "Bridge",
                "name=self-bridge-keep",
                columns=("_uuid",),
            )["_uuid"],
        )


class TestReconfigured:
    def test_bridge_identity_is_recorded(self, snapshots):
        ovs = Ovsdb(Runner(), "ovs-vsctl")

        snapshots.save(
            "ovs-bridge-reconfigured",
            ovs.one(
                "Bridge",
                "name=self-bridge-keep",
                columns=("_uuid",),
            )["_uuid"],
        )


class TestResult:
    def test_git_refspec_is_configured(self, tree):
        tasks = (tree / "roles/ovs_setup/tasks/git.yml").read_text()

        assert (
            'refspec: "+{{ ovs_setup_git_version }}:refs/ovs-tmt/'
            '{{ ovs_setup_git_version }}"'
        ) in tasks

    def test_ovs_is_running(self):
        runner = Runner()

        assert runner.succeeds("ovs-vsctl", "show")
        assert shutil.which("ovs-vswitchd")
        assert shutil.which("ovsdb-server")
        assert processes(runner, "ovsdb-server")
        assert processes(runner, "ovs-vswitchd")

    def test_reusable_ovs_state(self, snapshots):
        runner = Runner()
        ovs = Ovsdb(runner, "ovs-vsctl")
        bridge_uuid = ovs.one(
            "Bridge",
            "name=self-bridge-keep",
            columns=("_uuid",),
        )["_uuid"]

        assert bridge_uuid == snapshots.load("ovs-bridge")
        assert bridge_uuid == snapshots.load("ovs-bridge-reconfigured")
        assert runner.succeeds("ovs-vsctl", "br-exists", "self-bridge-keep")
        assert not runner.succeeds("ovs-vsctl", "br-exists", "self-bridge-delete")
        assert runner.succeeds("ovs-vsctl", "br-exists", "self-bridge-new")
        assert external_id(runner, "self-managed") == "updated"
        assert external_id(runner, "self-delete") == ""
        assert external_id(runner, "self-unmanaged") == "preserve"
