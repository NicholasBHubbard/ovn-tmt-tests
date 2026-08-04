from ovn_test.command import Runner
from ovn_test.system import processes


class TestPreconditions:
    def test_ovs_is_not_running(self) -> None:
        runner = Runner()

        assert not runner.succeeds("ovs-vsctl", "show")
        assert not processes(runner, "ovs-vswitchd")
        assert not processes(runner, "ovsdb-server")


class TestResult:
    def test_ovs_is_running(self) -> None:
        runner = Runner()

        assert runner.succeeds("ovs-vsctl", "show")
        assert processes(runner, "ovsdb-server")
        assert processes(runner, "ovs-vswitchd")
