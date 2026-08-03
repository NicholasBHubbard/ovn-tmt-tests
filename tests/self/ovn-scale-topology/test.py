import os
import time
from collections.abc import Iterator
from typing import Any

import pytest
from ovn_test.command import Runner
from ovn_test.config import read_int
from ovn_test.ovsdb import Ovsdb
from ovn_test.scale_topology import ScaleTopology
from ovn_test.state import Snapshots

OWNER = "external_ids:ovn-tmt-tests-owner="
SCOPE = "external_ids:ovn-tmt-tests-scope="


@pytest.fixture(scope="session")
def runner() -> Runner:
    return Runner()


@pytest.fixture(scope="session")
def scale(runner: Runner) -> Iterator[ScaleTopology]:
    environment = {
        **os.environ,
        "OTT_SCALE_ID": "self-scale",
        "OTT_SCALE_WORKERS": "3",
    }
    instance = ScaleTopology.from_environment(
        runner,
        [SCALE_CHASSIS],
        environment,
    )
    yield instance
    instance.cleanup()


@pytest.fixture
def nb(runner: Runner) -> Ovsdb:
    return Ovsdb(runner, "ovn-nbctl")


@pytest.fixture
def sb(runner: Runner) -> Ovsdb:
    return Ovsdb(runner, "ovn-sbctl")


def scale_rows(nb: Ovsdb, table: str) -> list[dict[str, Any]]:
    return nb.find(table, f"{OWNER}self-scale", columns=("_uuid", "name"))


def scale_managed_rows(nb: Ovsdb, table: str) -> list[dict[str, Any]]:
    return [
        row
        for row in nb.find(table, columns=("_uuid", "external_ids"))
        if row["external_ids"].get("ovn-tmt-tests-id", "").startswith("self-scale:")
    ]


def scale_gateway_rows(nb: Ovsdb) -> list[dict[str, Any]]:
    return [
        row
        for row in nb.find("Gateway_Chassis", columns=("_uuid", "name"))
        if row["name"].startswith("self-scale:")
    ]


def assert_scale_counts(nb: Ovsdb, workers: Any) -> None:
    assert len(scale_rows(nb, "Logical_Switch")) == 1 + 2 * workers
    assert len(scale_rows(nb, "Logical_Router")) == 1 + workers
    assert len(scale_rows(nb, "Logical_Router_Port")) == 1 + 3 * workers
    assert len(scale_gateway_rows(nb)) == workers
    assert len(scale_managed_rows(nb, "NAT")) == 2 * workers
    assert (
        len(
            nb.find(
                "Logical_Router_Static_Route",
                f"{SCOPE}self-scale",
                columns=("_uuid",),
            )
        )
        == 6 * workers
    )


def assert_scale_group_attachments(nb: Ovsdb, workers: Any) -> None:
    group = nb.by_name(
        "Load_Balancer_Group",
        "cluster-lb-group1",
        "_uuid",
        "name",
    )
    assert group["name"] == "cluster-lb-group1"
    assert set(
        nb.referring_names("Logical_Switch", "load_balancer_group", group["_uuid"])
    ) == {f"lswitch-ovn-scale-{index}" for index in range(workers)}
    assert set(
        nb.referring_names("Logical_Router", "load_balancer_group", group["_uuid"])
    ) == {f"gwrouter-ovn-scale-{index}" for index in range(workers)}


def assert_scale_external_vlans(nb: Ovsdb, workers: Any) -> None:
    for index in {0, workers - 1}:
        port = nb.by_name(
            "Logical_Switch_Port",
            f"provnet-ovn-scale-{index}",
            "tag",
            "tag_request",
        )
        assert port["tag"] == index + 1
        assert port["tag_request"] == index + 1


def scale_southbound_names(workers: Any) -> tuple[set[str], set[str]]:
    names = [f"ovn-scale-{index}" for index in range(workers)]
    datapaths = {"ls-join1", "lr-cluster1"}
    ports = {"ls-join1-to-rtr"}
    for name in names:
        datapaths.update(
            {
                f"lswitch-{name}",
                f"ext-{name}",
                f"gwrouter-{name}",
            }
        )
        ports.update(
            {
                f"node-to-rtr-{name}",
                f"join-to-gw-{name}",
                f"ext-to-gw-{name}",
                f"provnet-{name}",
            }
        )
    return datapaths, ports


def southbound_names(sb: Ovsdb) -> tuple[set[Any], set[Any]]:
    datapaths = {
        external_ids.get("name")
        for external_ids in sb.values("Datapath_Binding", "external_ids")
    }
    ports = set(sb.values("Port_Binding", "logical_port"))
    return datapaths - {None}, ports


def assert_scale_southbound(sb: Ovsdb, workers: Any) -> None:
    expected_datapaths, expected_ports = scale_southbound_names(workers)
    datapaths, ports = southbound_names(sb)
    assert expected_datapaths <= datapaths
    assert expected_ports <= ports


SCALE_CHASSIS = "ovn-scale-0"


def scale_chassis_sync(runner: Runner) -> int:
    timeout = read_int(os.environ, "OTT_SCALE_CHASSIS_TIMEOUT", 120)
    start = time.monotonic()
    runner.run(
        "ovn-nbctl",
        "--wait=hv",
        f"--timeout={timeout}",
        "sync",
    )
    print(f"Scale chassis sync completed in {time.monotonic() - start:.3f}s.")
    return timeout


def assert_scale_chassis(runner: Runner, nb: Ovsdb, sb: Ovsdb) -> str:
    timeout = scale_chassis_sync(runner)
    nb_cfg = nb.value("NB_Global", "nb_cfg")
    row = sb.by_name("Chassis", SCALE_CHASSIS, "_uuid")
    private = sb.by_name("Chassis_Private", SCALE_CHASSIS, "nb_cfg")
    assert private["nb_cfg"] >= nb_cfg
    assert (
        runner.output(
            "ovn-appctl",
            "-t",
            "ovn-controller",
            "connection-status",
        )
        == "connected"
    )

    logical_port = f"cr-rtr-to-node-{SCALE_CHASSIS}"
    runner.wait(
        "ovn-sbctl",
        "--bare",
        "--columns=chassis",
        "find",
        "Port_Binding",
        f"logical_port={logical_port}",
        attempts=timeout * 5,
        interval=0.2,
        until=lambda result, uuid=row["_uuid"]: uuid in result.stdout,
    )
    binding = sb.one(
        "Port_Binding",
        f"logical_port={logical_port}",
        "type=chassisredirect",
        columns=("chassis",),
    )
    assert binding["chassis"] == row["_uuid"]
    return row["_uuid"]


class TestPreconditions:
    def test_northbound_database_is_available(self) -> None:
        assert Runner().succeeds("ovn-nbctl", "show")


class TestInitial:
    @pytest.fixture(scope="class", autouse=True)
    def apply_topology(self, scale: ScaleTopology) -> None:
        scale.create(3)

    def test_three_workers_are_complete(
        self,
        runner: Runner,
        nb: Ovsdb,
        sb: Ovsdb,
        snapshots: Snapshots,
    ) -> None:
        assert_scale_counts(nb, 3)
        assert_scale_group_attachments(nb, 3)
        assert_scale_external_vlans(nb, 3)
        assert_scale_southbound(sb, 3)

        assert sorted(
            nb.by_name(
                "Logical_Router_Port",
                "rtr-to-node-ovn-scale-0",
                "networks",
            )["networks"]
        ) == [
            "16.0.255.254/16",
            "16::ffff:ffff:ffff:fffe/64",
        ]
        assert sorted(
            nb.by_name(
                "Logical_Router_Port",
                "gw-to-join-ovn-scale-0",
                "networks",
            )["networks"]
        ) == [
            "30.0.255.253/16",
            "30::ffff:ffff:ffff:fffd/64",
        ]

        route = nb.managed(
            "Logical_Router_Static_Route",
            "self-scale:ovn-scale-0:worker-v4",
            "ip_prefix",
            "nexthop",
            "policy",
        )
        assert route == {
            "ip_prefix": "16.0.0.0/16",
            "nexthop": "30.0.255.253",
            "policy": "src-ip",
        }
        nat = nb.managed(
            "NAT",
            "self-scale:ovn-scale-0:snat-v4",
            "type",
            "external_ip",
            "logical_ip",
        )
        assert nat == {
            "type": "snat",
            "external_ip": "30.0.255.253",
            "logical_ip": "16.0.0.0/4",
        }
        snapshots.save("scale-chassis", assert_scale_chassis(runner, nb, sb))

    @pytest.mark.parametrize(
        ("table", "name", "snapshot"),
        (
            ("Logical_Switch", "ls-join1", "scale-join"),
            ("Logical_Router", "lr-cluster1", "scale-cluster"),
            (
                "Logical_Router_Port",
                "rtr-to-node-ovn-scale-0",
                "scale-worker-port",
            ),
        ),
    )
    def test_stable_identity_is_recorded(
        self, nb: Ovsdb, snapshots: Snapshots, table: str, name: str, snapshot: str
    ) -> None:
        snapshots.save(snapshot, nb.by_name(table, name, "_uuid")["_uuid"])


class TestExpanded:
    @pytest.fixture(scope="class", autouse=True)
    def apply_topology(self, scale: ScaleTopology) -> None:
        scale.create(500)

    def test_500_workers_are_complete(
        self,
        runner: Runner,
        nb: Ovsdb,
        sb: Ovsdb,
        snapshots: Snapshots,
    ) -> None:
        assert_scale_counts(nb, 500)
        assert_scale_group_attachments(nb, 500)
        assert_scale_external_vlans(nb, 500)
        assert_scale_southbound(sb, 500)
        assert nb.by_name("Logical_Switch", "ls-join1", "_uuid")[
            "_uuid"
        ] == snapshots.load("scale-join")
        assert nb.by_name("Logical_Router", "lr-cluster1", "_uuid")[
            "_uuid"
        ] == snapshots.load("scale-cluster")
        assert nb.by_name(
            "Logical_Router_Port",
            "rtr-to-node-ovn-scale-0",
            "_uuid",
        )["_uuid"] == snapshots.load("scale-worker-port")
        assert sorted(
            nb.by_name(
                "Logical_Router_Port",
                "rtr-to-node-ovn-scale-499",
                "networks",
            )["networks"]
        ) == [
            "16::1f3:ffff:ffff:ffff:fffe/64",
            "17.243.255.254/16",
        ]
        assert assert_scale_chassis(runner, nb, sb) == snapshots.load("scale-chassis")


class TestResult:
    @pytest.fixture(scope="class", autouse=True)
    def apply_topology(self, scale: ScaleTopology) -> None:
        scale.create(2)

    def test_contracted_topology_is_complete(
        self,
        runner: Runner,
        nb: Ovsdb,
        sb: Ovsdb,
        snapshots: Snapshots,
    ) -> None:
        assert_scale_counts(nb, 2)
        assert_scale_group_attachments(nb, 2)
        assert_scale_external_vlans(nb, 2)
        assert_scale_southbound(sb, 2)
        assert nb.by_name("Logical_Switch", "ls-join1", "_uuid")[
            "_uuid"
        ] == snapshots.load("scale-join")
        assert nb.by_name("Logical_Router", "lr-cluster1", "_uuid")[
            "_uuid"
        ] == snapshots.load("scale-cluster")
        assert nb.by_name(
            "Logical_Router_Port",
            "rtr-to-node-ovn-scale-0",
            "_uuid",
        )["_uuid"] == snapshots.load("scale-worker-port")
        assert assert_scale_chassis(runner, nb, sb) == snapshots.load("scale-chassis")

    def test_removed_workers_leave_no_southbound_topology(self, sb: Ovsdb) -> None:
        current_datapaths, current_ports = scale_southbound_names(2)
        expanded_datapaths, expanded_ports = scale_southbound_names(500)
        datapaths, ports = southbound_names(sb)

        assert not (expanded_datapaths - current_datapaths) & datapaths
        assert not (expanded_ports - current_ports) & ports

    @pytest.mark.parametrize(
        "name",
        ("ovn-scale-2", "ovn-scale-3", "ovn-scale-4"),
    )
    def test_removed_workers_leave_no_topology(self, nb: Ovsdb, name: str) -> None:
        assert not nb.exists("Logical_Switch", f"name=lswitch-{name}")
        assert not nb.exists("Logical_Switch", f"name=ext-{name}")
        assert not nb.exists("Logical_Router", f"name=gwrouter-{name}")
        assert not nb.exists(
            "Logical_Router_Port",
            f"name=rtr-to-node-{name}",
        )
        assert not scale_managed_rows(nb, "NAT") or all(
            name not in row["external_ids"]["ovn-tmt-tests-id"]
            for row in scale_managed_rows(nb, "NAT")
        )


class TestCleanup:
    @pytest.fixture(scope="class", autouse=True)
    def remove_topology(self, scale: ScaleTopology) -> None:
        scale.cleanup()

    def test_all_managed_state_is_removed(self, nb: Ovsdb, sb: Ovsdb) -> None:
        for table in (
            "Logical_Switch",
            "Logical_Router",
            "Logical_Router_Port",
        ):
            assert not scale_rows(nb, table)
        assert not scale_gateway_rows(nb)
        assert not scale_managed_rows(nb, "NAT")
        assert not nb.find(
            "Logical_Router_Static_Route",
            f"{SCOPE}self-scale",
            columns=("_uuid",),
        )
        assert not nb.exists("Load_Balancer_Group", 'name="cluster-lb-group1"')

        expected_datapaths, expected_ports = scale_southbound_names(2)
        datapaths, ports = southbound_names(sb)
        assert not expected_datapaths & datapaths
        assert not expected_ports & ports
