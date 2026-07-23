import hashlib

import pytest

from ovn_test.command import Runner
from ovn_test.network import Network


ENDPOINTS = (
    "self-direct",
    "self-peer",
    "self-delete",
    "self-away",
    "self-stale",
    "self-keep",
    "self-long-endpoint-name",
)


@pytest.fixture
def runner():
    return Runner()


@pytest.fixture
def network(runner):
    return Network(runner)


def bridge(runner, interface):
    return runner.output("ovs-vsctl", "port-to-br", interface)


def long_host_interface():
    digest = hashlib.sha1(b"self-long-endpoint-name", usedforsecurity=False).hexdigest()
    return f"ovse-{digest[:10]}"


def identity(runner, name):
    return runner.output("stat", "-Lc", "%i", f"/var/run/netns/{name}")


def host_ifindex(runner, interface):
    return runner.output("cat", f"/sys/class/net/{interface}/ifindex")


class TestPreconditions:
    @pytest.mark.parametrize("bridge_name", ("self-br-a", "self-br-b"))
    def test_bridge_is_absent(self, runner, bridge_name):
        assert not runner.succeeds("ovs-vsctl", "br-exists", bridge_name)

    @pytest.mark.parametrize("endpoint", ENDPOINTS)
    def test_endpoint_is_absent(self, network, endpoint):
        assert not network.namespace_exists(endpoint)
        assert network.link(f"{endpoint}-p") is None

    def test_shortened_host_interface_is_absent(self, network):
        assert network.link(long_host_interface()) is None


class TestInitial:
    def test_attachments(self, runner):
        assert bridge(runner, "self-direct-p") == "self-br-a"
        assert bridge(runner, "self-peer-p") == "self-br-a"
        assert bridge(runner, long_host_interface()) == "self-br-a"

    def test_long_endpoint(self, network):
        link = network.link("inside0", "self-long-endpoint-name")
        assert link["address"] == "02:00:00:00:20:07"

    @pytest.mark.parametrize(
        ("endpoint", "mtu"),
        (("self-direct", 1400), ("self-peer", 1450)),
    )
    def test_mtu(self, network, endpoint, mtu):
        assert network.link(f"{endpoint}-p")["mtu"] == mtu
        assert network.link(endpoint, endpoint)["mtu"] == mtu

    def test_direct_endpoint(self, runner, network):
        link = network.link("self-direct", "self-direct")
        assert link["address"] == "02:00:00:00:20:01"
        assert sorted(
            network.addresses("self-direct", "self-direct", scope="global")
        ) == ["192.0.2.10/24", "2001:db8:1::10/64"]
        runner.namespace("self-direct", "ping", "-c", "1", "-W", "2", "192.0.2.20")
        runner.namespace(
            "self-long-endpoint-name",
            "ping",
            "-c",
            "1",
            "-W",
            "2",
            "192.0.2.20",
        )

    def test_routes(self, network):
        assert (
            network.routes("self-direct", 4, "main", "default")[0]["gateway"]
            == "192.0.2.1"
        )
        route = network.routes("self-direct", 4, 100, "198.51.100.0/24")[0]
        assert route["gateway"] == "192.0.2.2"
        assert route["metric"] == 10
        assert (
            network.routes("self-direct", 6, 200, "default")[0]["gateway"]
            == "2001:db8:1::1"
        )

    def test_identity_is_recorded(self, runner, snapshots):
        snapshots.save("ovs-endpoint-ns", identity(runner, "self-direct"))
        snapshots.save(
            "ovs-endpoint-ifindex",
            host_ifindex(runner, "self-direct-p"),
        )


class TestReconfigured:
    def test_identity_is_recorded(self, runner, snapshots):
        snapshots.save(
            "ovs-endpoint-reconfigured-ns",
            identity(runner, "self-direct"),
        )
        snapshots.save(
            "ovs-endpoint-reconfigured-ifindex",
            host_ifindex(runner, "self-direct-p"),
        )


class TestResult:
    @pytest.mark.parametrize("endpoint", ("self-direct", "self-peer"))
    def test_endpoints_moved_bridges(self, runner, network, endpoint):
        assert network.namespace_exists(endpoint)
        assert network.link(f"{endpoint}-p") is not None
        assert bridge(runner, f"{endpoint}-p") == "self-br-b"

    def test_long_endpoint_moved_bridges(self, runner, network):
        assert bridge(runner, long_host_interface()) == "self-br-b"
        link = network.link("endpoint0", "self-long-endpoint-name")
        assert link["address"] == "02:00:00:00:20:17"
        runner.namespace(
            "self-long-endpoint-name",
            "ping",
            "-c",
            "1",
            "-W",
            "2",
            "203.0.113.20",
        )

    @pytest.mark.parametrize(
        ("endpoint", "mtu"),
        (("self-direct", 1500), ("self-peer", 1300)),
    )
    def test_mtu(self, network, endpoint, mtu):
        assert network.link(f"{endpoint}-p")["mtu"] == mtu
        assert network.link(endpoint, endpoint)["mtu"] == mtu

    def test_direct_endpoint_reconfigured(self, runner, network):
        link = network.link("self-direct", "self-direct")
        assert link["address"] == "02:00:00:00:20:11"
        assert network.addresses("self-direct", "self-direct", scope="global") == [
            "203.0.113.10/24"
        ]
        runner.namespace("self-direct", "ping", "-c", "1", "-W", "2", "203.0.113.20")

    def test_routes_replaced(self, network):
        assert (
            network.routes("self-direct", 4, "main", "default")[0]["gateway"]
            == "203.0.113.1"
        )
        route = network.routes("self-direct", 4, 101, "198.51.100.0/24")[0]
        assert route["gateway"] == "203.0.113.2"
        assert route["metric"] == 20
        assert network.routes("self-direct", 4, 100) == []
        assert network.routes("self-direct", 6, 200) == []

    def test_identity_was_preserved(self, runner, snapshots):
        namespace = identity(runner, "self-direct")
        ifindex = host_ifindex(runner, "self-direct-p")
        assert namespace == snapshots.load("ovs-endpoint-ns")
        assert namespace == snapshots.load("ovs-endpoint-reconfigured-ns")
        assert ifindex == snapshots.load("ovs-endpoint-ifindex")
        assert ifindex == snapshots.load("ovs-endpoint-reconfigured-ifindex")

    @pytest.mark.parametrize("endpoint", ("self-delete", "self-away", "self-stale"))
    def test_removed_endpoints_are_absent(self, runner, network, endpoint):
        interface = f"{endpoint}-p"
        assert not network.namespace_exists(endpoint)
        assert network.link(interface) is None
        assert not runner.succeeds("ovs-vsctl", "port-to-br", interface)

    def test_unlisted_endpoint_is_unchanged(self, runner, network):
        assert bridge(runner, "self-keep-p") == "self-br-a"
        assert network.link("self-keep", "self-keep")["mtu"] == 1450
