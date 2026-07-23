import shutil

from ovn_test.command import Runner
from ovn_test.system import processes


class TestPreconditions:
    def test_ovs_is_not_configured(self):
        runner = Runner()

        assert not runner.succeeds("ovs-vsctl", "show")
        assert not processes(runner, "ovs-vswitchd")
        assert not processes(runner, "ovsdb-server")


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
