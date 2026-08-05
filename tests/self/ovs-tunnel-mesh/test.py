import ipaddress
from typing import Any

import pytest
from ovn_test.command import Runner
from ovn_test.network import Network
from ovn_test.ovsdb import Ovsdb
from ovn_test.state import Snapshots

ENDPOINTS = {
    "self-mesh-1": "192.0.2.1",
    "self-mesh-2": "192.0.2.2",
}


@pytest.fixture
def runner() -> Runner:
    return Runner()


@pytest.fixture
def network(runner: Runner) -> Network:
    return Network(runner)


@pytest.fixture
def ovs(runner: Runner) -> Ovsdb:
    return Ovsdb(runner, "ovs-vsctl")


def local_endpoint(network: Network) -> tuple[str, str]:
    matches = [
        (name, address)
        for name, address in ENDPOINTS.items()
        if network.namespace_exists(name)
    ]
    if len(matches) != 1:
        raise AssertionError(f"expected one local endpoint, found {matches}")
    return matches[0]


def mesh_ports(ovs: Ovsdb, mesh: str) -> list[dict[str, Any]]:
    return ovs.find(
        "Interface",
        f"external_ids:ovn-tmt-tests-mesh={mesh}",
        columns=("_uuid", "name", "type", "options", "external_ids"),
    )


def port_identity(ovs: Ovsdb, mesh: str) -> str:
    return ",".join(sorted(row["_uuid"] for row in mesh_ports(ovs, mesh)))


def assert_mesh(
    ovs: Ovsdb,
    mesh: str,
    count: int,
    tunnel_type: str,
    key: str,
    bridge: str,
) -> list[dict[str, Any]]:
    ports = mesh_ports(ovs, mesh)
    assert len(ports) == count
    for port in ports:
        assert port["type"] == tunnel_type
        assert port["options"]["key"] == key
        assert ipaddress.ip_address(port["options"]["remote_ip"])
        assert ovs.runner.output("ovs-vsctl", "port-to-br", port["name"]) == bridge
    return ports


def assert_connectivity(network: Network) -> None:
    namespace, local_address = local_endpoint(network)
    for address in ENDPOINTS.values():
        if address != local_address:
            network.wait_for_ping(namespace, address)


class TestPreconditions:
    @pytest.mark.parametrize(
        "bridge", ("self-full-a", "self-full-b", "self-hub", "self-gre")
    )
    def test_bridge_is_absent(self, runner: Runner, bridge: str) -> None:
        assert not runner.succeeds("ovs-vsctl", "br-exists", bridge)


class TestInitial:
    def test_full_mesh(self, ovs: Ovsdb, snapshots: Snapshots) -> None:
        assert_mesh(ovs, "self-full", 1, "geneve", "101", "self-full-a")
        snapshots.save("ovs-tunnel-mesh-identity", port_identity(ovs, "self-full"))

    def test_hub_mesh(self, ovs: Ovsdb) -> None:
        ports = mesh_ports(ovs, "self-hub")
        assert_mesh(ovs, "self-hub", 1, "vxlan", "102", "self-hub")
        for port in ports:
            peer = port["external_ids"]["ovn-tmt-tests-peer"]
            index = peer.removeprefix("mesh-")
            assert port["options"]["remote_ip"] == f"127.0.0.1{index}"

    def test_gre_mesh(self, ovs: Ovsdb) -> None:
        assert_mesh(ovs, "self-gre", 1, "gre", "16777216", "self-gre")

    def test_connectivity(self, network: Network) -> None:
        assert_connectivity(network)


class TestReapplied:
    def test_port_identity_was_preserved(
        self, ovs: Ovsdb, snapshots: Snapshots
    ) -> None:
        assert port_identity(ovs, "self-full") == snapshots.load(
            "ovs-tunnel-mesh-identity"
        )


class TestResult:
    def test_full_mesh_was_moved_and_updated(self, ovs: Ovsdb) -> None:
        assert_mesh(ovs, "self-full", 1, "geneve", "201", "self-full-b")

    def test_hub_mesh_was_removed(self, ovs: Ovsdb) -> None:
        assert mesh_ports(ovs, "self-hub") == []

    def test_gre_mesh_was_removed(self, ovs: Ovsdb) -> None:
        assert mesh_ports(ovs, "self-gre") == []

    def test_reconfigured_connectivity(self, network: Network) -> None:
        assert_connectivity(network)
