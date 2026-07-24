import os

import pytest

from ovn_test.ansible import Ansible
from ovn_test.command import Runner
from ovn_test.ovsdb import Ovsdb
from ovn_test.system import processes
from ovn_test.topology import Topology


@pytest.fixture
def topology():
    return Topology.from_environment()


@pytest.fixture
def runner(topology):
    return Runner(topology)


@pytest.fixture
def nb(runner):
    return Ovsdb(runner, "ovn-nbctl")


@pytest.fixture
def sb(runner):
    return Ovsdb(runner, "ovn-sbctl")


def ping(runner, guest, namespace, destination):
    runner.wait(
        "ip",
        "netns",
        "exec",
        namespace,
        "ping",
        "-q",
        "-c",
        "1",
        "-W",
        "1",
        destination,
        guest=guest,
        attempts=30,
    )


def connection(runner, database):
    return runner.output(database, "get-connection")


def ssl_configuration(runner, database, guest=None):
    return runner.output(database, "get-ssl", guest=guest)


class TestPreconditions:
    @pytest.mark.parametrize("process", ("ovn-northd", "ovn-controller"))
    def test_ovn_process_is_absent(self, runner, process):
        assert processes(runner, process) == []

    def test_southbound_database_is_unavailable(self, runner):
        assert not runner.succeeds("ovn-sbctl", "show")


class TestTLS:
    def test_databases_use_tls(self, runner):
        assert "pssl:" in connection(runner, "ovn-nbctl")
        assert "pssl:" in connection(runner, "ovn-sbctl")

    def test_compute_chassis_use_tls(self, runner, topology):
        for guest in topology.role("compute"):
            remote = runner.output(
                "ovs-vsctl",
                "get",
                "Open_vSwitch",
                ".",
                "external_ids:ovn-remote",
                guest=guest,
            ).strip('"')
            assert remote.startswith("ssl:")
            runner.run(
                "test",
                "-s",
                "/run/ovn-test-pki/certificate.pem",
                guest=guest,
            )

    @pytest.mark.parametrize("database", ("ovn-nbctl", "ovn-sbctl"))
    def test_remote_database_connection(self, runner, topology, database):
        port = "6641" if database == "ovn-nbctl" else "6642"
        runner.run(
            database,
            f"--db=ssl:{topology.hostname('central')}:{port}",
            "--private-key=/run/ovn-test-pki/private-key.pem",
            "--certificate=/run/ovn-test-pki/certificate.pem",
            "--ca-cert=/run/ovn-test-pki/ca-cert.pem",
            "show",
            guest="compute-1",
        )

    def test_packet_traffic(self, runner):
        ping(runner, "compute-1", "self-tls-a", "192.0.2.22")


class TestTCP:
    def test_databases_returned_to_tcp(self, runner):
        assert "ptcp:" in connection(runner, "ovn-nbctl")
        assert "ptcp:" in connection(runner, "ovn-sbctl")
        assert ssl_configuration(runner, "ovn-nbctl") == ""
        assert ssl_configuration(runner, "ovn-sbctl") == ""

    def test_compute_chassis_returned_to_tcp(self, runner, topology):
        for guest in topology.role("compute"):
            remote = runner.output(
                "ovs-vsctl",
                "get",
                "Open_vSwitch",
                ".",
                "external_ids:ovn-remote",
                guest=guest,
            ).strip('"')
            assert remote.startswith("tcp:")

    def test_pki_state_is_removed(self, runner, topology):
        for guest in topology.guests():
            assert ssl_configuration(runner, "ovs-vsctl", guest=guest) == ""
            assert not runner.succeeds("test", "-e", "/run/ovn-test-pki", guest=guest)

    def test_packet_traffic(self, runner):
        ping(runner, "compute-1", "self-tls-a", "192.0.2.22")


class TestResult:
    def test_test_scoped_ansible_execution(self, topology, test_data):
        ansible = Ansible.from_environment(topology=topology)
        ansible.run("tests/self/multihost/ansible-execution.yml")
        marker = "TASK [Confirm test-scoped Ansible execution reaches each guest]"
        assert marker in (test_data / "setup.log").read_text()
        for guest in topology.guests():
            log = (test_data / f"setup-{guest}.log").read_text()
            assert marker in log
            recaps = [line.split()[0] for line in log.splitlines() if " : ok=" in line]
            assert recaps == [guest]

    def test_central_services(self, runner):
        assert processes(runner, "ovsdb-server")
        assert processes(runner, "ovn-northd")
        runner.run("ovn-nbctl", "show")
        runner.run("ovn-sbctl", "show")

    def test_chassis_registration(self, sb):
        chassis = sb.find("Chassis", columns=("name",))
        assert chassis
        expected = os.environ.get("OTT_EXPECTED_CHASSIS")
        if expected is not None:
            assert len(chassis) == int(expected)

    def test_cross_guest_execution(self, runner):
        guest = os.environ.get("OTT_MULTIHOST_TEST_GUEST")
        if guest is None:
            pytest.skip("no cross-guest target configured")
        assert runner.output("hostname", guest=guest)
        assert not runner.succeeds("false", guest=guest)

    def test_provider_mesh_connectivity(self, runner):
        if os.environ.get("OTT_EXPECTED_CHASSIS") != "2":
            pytest.skip("provider mesh belongs to the standard plan")
        ping(runner, "compute-1", "self-provider-1", "192.0.2.2")
        ping(runner, "central", "self-provider-0", "192.0.2.2")

    @pytest.mark.parametrize(
        ("guest", "expected"),
        (("central", 1), ("compute-1", 2), ("compute-2", 1)),
    )
    def test_provider_mesh_tunnels(self, runner, guest, expected):
        if os.environ.get("OTT_EXPECTED_CHASSIS") != "2":
            pytest.skip("provider mesh belongs to the standard plan")
        output = runner.output(
            "ovs-vsctl",
            "--bare",
            "--columns=name",
            "find",
            "Interface",
            "external_ids:ovn-tmt-tests-mesh=self-provider",
            guest=guest,
        )
        assert len(output.split()) == expected

    def test_inventory_name_fallback(self, runner, tree, test_data):
        inventory = test_data / "fallback-inventory.ini"
        inventory.write_text(
            "[central]\n"
            "central-node ansible_connection=local\n\n"
            "[compute]\n"
            "compute-node ansible_connection=local\n"
        )
        result = runner.run(
            "ansible-playbook",
            "-v",
            "-i",
            inventory,
            "playbooks/multihost.yml",
            "--check",
            "--tags",
            "topology-resolution",
            "-e",
            "ansible_become=false",
            cwd=tree,
        )
        assert '"ovn_central_address": "central-node"' in result.stdout
