import hashlib
from pathlib import Path
from typing import Any

import pytest
from ovn_test.command import Runner
from ovn_test.network import Network
from ovn_test.ovsdb import Ovsdb
from ovn_test.state import Snapshots

ENDPOINTS = ("self-vm1", "self-vm2", "self-remote", "self-delete")


@pytest.fixture
def runner() -> Runner:
    return Runner()


@pytest.fixture
def network(runner: Runner) -> Network:
    return Network(runner)


@pytest.fixture
def nb(runner: Runner) -> Ovsdb:
    return Ovsdb(runner, "ovn-nbctl")


@pytest.fixture
def ovs(runner: Runner) -> Ovsdb:
    return Ovsdb(runner, "ovs-vsctl")


def namespace_identity(runner: Runner, name: str) -> str:
    return runner.output("stat", "-Lc", "%i", f"/var/run/netns/{name}")


def host_ifindex(runner: Runner, interface: str) -> str:
    return runner.output("cat", f"/sys/class/net/{interface}/ifindex")


def process_arguments(runner: Runner, pid: str) -> str:
    return runner.output("ps", "-p", pid, "-o", "args=", check=False)


def assert_logical_port(
    nb: Ovsdb, name: str, switch: Any, mac: str, addresses: Any
) -> None:
    port = nb.by_name("Logical_Switch_Port", name, "_uuid", "addresses")
    assert nb.referring_names("Logical_Switch", "ports", port["_uuid"]) == [switch]
    assert port["addresses"] == " ".join((mac, *addresses))


class TestPreconditions:
    @pytest.mark.parametrize("endpoint", ENDPOINTS)
    def test_endpoint_is_absent(self, network: Network, endpoint: Any) -> None:
        assert not network.namespace_exists(endpoint)
        assert network.link(f"{endpoint}-p") is None


class TestHostState:
    def test_host_resolver_is_recorded(self, snapshots: Snapshots) -> None:
        content = Path("/etc/resolv.conf").read_bytes()
        snapshots.save(
            "ovn-endpoint-resolver",
            hashlib.sha256(content).hexdigest(),
        )

    def test_namespace_fixture_is_created(self) -> None:
        path = Path("/etc/netns/self-vm1/preserve")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
        assert path.is_file()


class TestInitial:
    def test_port_state_is_recorded(self, nb: Ovsdb, snapshots: Snapshots) -> None:
        port = nb.by_name(
            "Logical_Switch_Port",
            "self-port3",
            "_uuid",
        )
        dynamic = nb.by_name(
            "Logical_Switch_Port",
            "self-port2",
            "dynamic_addresses",
        )["dynamic_addresses"]
        snapshots.save("ovn-endpoint-port", port["_uuid"])
        snapshots.save("ovn-endpoint-dynamic-address", dynamic.split()[1])

    @pytest.mark.parametrize(
        ("endpoint", "mtu"),
        (("self-vm1", 1400), ("self-vm2", 1450)),
    )
    def test_mtu(self, network: Network, endpoint: Any, mtu: int) -> None:
        assert network.require_link(f"{endpoint}-p")["mtu"] == mtu
        assert network.require_link(endpoint, endpoint)["mtu"] == mtu

    def test_identity_is_recorded(self, runner: Runner, snapshots: Snapshots) -> None:
        snapshots.save(
            "ovn-endpoint-ns",
            namespace_identity(runner, "self-vm1"),
        )
        snapshots.save(
            "ovn-endpoint-ifindex",
            host_ifindex(runner, "self-vm1-p"),
        )

    def test_port_configuration(self, nb: Ovsdb) -> None:
        assert (
            nb.by_name("Logical_Switch_Port", "self-port3", "addresses")["addresses"]
            == "02:00:00:00:03:01 dynamic"
        )
        options = nb.by_name("Logical_Switch_Port", "self-port1", "options")["options"]
        assert options["requested-chassis"] == "default-0"
        assert options["mcast_flood"] == "false"

    def test_dhcp_options(self, nb: Ovsdb) -> None:
        port = nb.by_name(
            "Logical_Switch_Port",
            "self-port3",
            "dhcpv4_options",
            "dhcpv6_options",
        )
        dhcp4 = nb.managed("DHCP_Options", "self-dhcp", "_uuid")
        dhcp6 = nb.managed("DHCP_Options", "self-dhcp-v6", "_uuid")
        assert port["dhcpv4_options"] == dhcp4["_uuid"]
        assert port["dhcpv6_options"] == dhcp6["_uuid"]

    def test_dhcp_lease(
        self, runner: Runner, network: Network, snapshots: Snapshots
    ) -> None:
        address = snapshots.load("ovn-endpoint-dynamic-address")
        assert network.addresses("self-vm2", "self-vm2", scope="global") == [
            f"{address}/24"
        ]
        assert (
            network.routes("self-vm2", 4, "main", "default")[0]["gateway"]
            == "192.0.2.254"
        )

        pid_file = Path("/run/ovn-tmt-tests/self-vm2-dhclient4.pid")
        lease_file = Path("/run/ovn-tmt-tests/self-vm2-dhclient4.leases")
        assert pid_file.stat().st_size
        assert lease_file.stat().st_size
        pid = pid_file.read_text().strip()
        old_pid = Path("/tmp/self-vm2-initial-dhclient4-pid").read_text().strip()
        assert pid != old_pid
        assert "dhclient" not in process_arguments(runner, old_pid)
        assert runner.succeeds("kill", "-0", pid)
        assert "--timeout 10" in process_arguments(runner, pid)
        snapshots.save("ovn-endpoint-dhcp-pid", pid)

    def test_dhcp_resolver(self, snapshots: Snapshots) -> None:
        resolver = Path("/etc/netns/self-vm2/resolv.conf")
        assert "nameserver 192.0.2.53" in resolver.read_text()
        host_hash = hashlib.sha256(Path("/etc/resolv.conf").read_bytes()).hexdigest()
        assert host_hash == snapshots.load("ovn-endpoint-resolver")


class TestReconfigured:
    def test_identity_is_recorded(self, runner: Runner, snapshots: Snapshots) -> None:
        snapshots.save(
            "ovn-endpoint-reconfigured-ns",
            namespace_identity(runner, "self-vm1"),
        )
        snapshots.save(
            "ovn-endpoint-reconfigured-ifindex",
            host_ifindex(runner, "self-vm1-p"),
        )


class TestResult:
    def test_vm1(self, runner: Runner, network: Network, nb: Ovsdb, ovs: Ovsdb) -> None:
        assert_logical_port(
            nb,
            "self-port1",
            "self-moved",
            "02:00:00:00:01:02",
            ("192.0.2.10", "2001:db8:2::1"),
        )
        assert network.namespace_exists("self-vm1")
        assert network.link("self-vm1-p") is not None
        assert ovs.value("Port", "name", "name=self-vm1-p") == "self-vm1-p"
        assert runner.output("ovs-vsctl", "port-to-br", "self-vm1-p") == "self-br"
        assert (
            ovs.value(
                "Interface",
                "external_ids",
                "name=self-vm1-p",
            )["iface-id"]
            == "self-port1"
        )
        assert (
            network.require_link("self-vm1", "self-vm1")["address"]
            == "02:00:00:00:01:02"
        )
        assert sorted(network.addresses("self-vm1", "self-vm1", scope="global")) == [
            "192.0.2.10/24",
            "2001:db8:2::1/64",
        ]

    def test_vm1_options(self, nb: Ovsdb) -> None:
        options = nb.by_name("Logical_Switch_Port", "self-port1", "options")["options"]
        assert options == {"requested-chassis": "another-host"}

    def test_other_ports(self, nb: Ovsdb) -> None:
        assert_logical_port(
            nb,
            "self-port2",
            "self-moved",
            "02:00:00:00:02:01",
            ("192.0.2.2",),
        )
        assert_logical_port(
            nb,
            "self-port3",
            "self-moved",
            "02:00:00:00:03:02",
            (),
        )

    def test_remote_endpoint_is_realized(
        self, runner: Runner, network: Network, ovs: Ovsdb
    ) -> None:
        assert network.namespace_exists("self-remote")
        assert network.link("self-remote-p") is not None
        assert runner.output("ovs-vsctl", "port-to-br", "self-remote-p") == "self-br"
        assert (
            ovs.value(
                "Interface",
                "external_ids",
                "name=self-remote-p",
            )["iface-id"]
            == "self-port3"
        )
        assert (
            network.require_link("self-remote", "self-remote")["address"]
            == "02:00:00:00:03:02"
        )
        assert network.addresses("self-remote", "self-remote", scope="global") == []

    @pytest.mark.parametrize(
        ("endpoint", "mtu"),
        (("self-vm1", 1500), ("self-remote", 1300)),
    )
    def test_mtu(self, network: Network, endpoint: Any, mtu: int) -> None:
        assert network.require_link(f"{endpoint}-p")["mtu"] == mtu
        assert network.require_link(endpoint, endpoint)["mtu"] == mtu

    def test_deleted_port_and_dhcp_links(self, nb: Ovsdb) -> None:
        assert not nb.exists("Logical_Switch_Port", "name=self-port4")
        port = nb.by_name(
            "Logical_Switch_Port",
            "self-port3",
            "dhcpv4_options",
            "dhcpv6_options",
        )
        assert port["dhcpv4_options"] == []
        assert port["dhcpv6_options"] == []

    def test_port_identity_was_preserved(self, nb: Ovsdb, snapshots: Snapshots) -> None:
        assert nb.by_name(
            "Logical_Switch_Port",
            "self-port3",
            "_uuid",
        )["_uuid"] == snapshots.load("ovn-endpoint-port")

    def test_endpoint_identity_was_preserved(
        self, runner: Runner, snapshots: Snapshots
    ) -> None:
        namespace = namespace_identity(runner, "self-vm1")
        ifindex = host_ifindex(runner, "self-vm1-p")
        assert namespace == snapshots.load("ovn-endpoint-ns")
        assert namespace == snapshots.load("ovn-endpoint-reconfigured-ns")
        assert ifindex == snapshots.load("ovn-endpoint-ifindex")
        assert ifindex == snapshots.load("ovn-endpoint-reconfigured-ifindex")

    def test_routes_replaced(self, network: Network) -> None:
        assert (
            network.routes("self-vm1", 4, "main", "default")[0]["gateway"]
            == "192.0.2.1"
        )
        assert (
            network.routes("self-vm1", 4, 101, "203.0.113.0/24")[0]["gateway"]
            == "192.0.2.2"
        )
        assert network.routes("self-vm1", 4, 100) == []
        assert network.routes("self-vm1", 6, "main", "default") == []
        assert network.routes("self-vm1", 6, 200, "default") == []

    @pytest.mark.parametrize("endpoint", ("self-vm2", "self-delete"))
    def test_removed_endpoints_are_absent(
        self, network: Network, endpoint: Any
    ) -> None:
        assert not network.namespace_exists(endpoint)
        assert network.link(f"{endpoint}-p") is None

    def test_dhcp_state_removed(self, runner: Runner, snapshots: Snapshots) -> None:
        pid = snapshots.load("ovn-endpoint-dhcp-pid")
        assert "dhclient" not in process_arguments(runner, pid)
        assert not list(Path("/run/ovn-tmt-tests").glob("self-vm2-dhclient4.*"))
        assert not list(Path("/run/ovn-tmt-tests").glob("self-stale-dhcp-*"))
        assert not Path("/etc/netns/self-vm2").exists()

    def test_host_and_static_namespace_files(self, snapshots: Snapshots) -> None:
        host_hash = hashlib.sha256(Path("/etc/resolv.conf").read_bytes()).hexdigest()
        assert host_hash == snapshots.load("ovn-endpoint-resolver")
        assert Path("/etc/netns/self-vm1/preserve").is_file()
