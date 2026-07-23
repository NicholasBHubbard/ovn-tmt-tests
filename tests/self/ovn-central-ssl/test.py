from pathlib import Path

from ovn_test.command import Runner
from ovn_test.system import processes, tcp_listeners


class TestPreconditions:
    def test_services_are_absent(self):
        runner = Runner()

        assert not processes(runner, "ovn-northd")
        assert not runner.succeeds("ovn-nbctl", "show")
        assert not runner.succeeds("ovn-sbctl", "show")


class TestCredentials:
    def test_credentials_exist(self):
        root = Path("/etc/openvswitch")

        for name in ("ovn-privkey.pem", "ovn-cert.pem", "cacert.pem"):
            assert (root / name).is_file()


class TestResult:
    def test_tls_services_and_databases(self):
        runner = Runner()

        assert processes(runner, "ovsdb-server")
        assert processes(runner, "ovn-northd")
        assert runner.succeeds("ovn-nbctl", "show")
        assert runner.succeeds("ovn-sbctl", "show")
        assert tcp_listeners(runner, 6641)
        assert tcp_listeners(runner, 6642)
        assert "pssl:" in runner.output("ovn-nbctl", "get-connection")
        assert "pssl:" in runner.output("ovn-sbctl", "get-connection")
