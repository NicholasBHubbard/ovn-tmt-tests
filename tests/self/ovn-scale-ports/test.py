import json
import os
import time
from typing import Any, Optional

import pytest
from ovn_test.command import Runner
from ovn_test.config import read_int
from ovn_test.ovsdb import Ovsdb
from ovn_test.state import Snapshots

OWNER = "external_ids:ovn-tmt-tests-owner="


@pytest.fixture
def runner() -> Runner:
    return Runner()


@pytest.fixture
def nb(runner: Runner) -> Ovsdb:
    return Ovsdb(runner, "ovn-nbctl")


@pytest.fixture
def sb(runner: Runner) -> Ovsdb:
    return Ovsdb(runner, "ovn-sbctl")


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


def scale_ports(count: int) -> list[dict[str, Any]]:
    result = []
    for index in range(count):
        mac = "02:0a:" + ":".join(
            f"{index >> shift & 255:02x}" for shift in (24, 16, 8, 0)
        )
        result.append(
            {
                "name": f"ovn-scale-pod-{index}",
                "interface": f"osp{index:08x}",
                "chassis": SCALE_CHASSIS,
                "switch": f"lswitch-{SCALE_CHASSIS}",
                "addresses": f"{mac} 16.0.0.{index + 1} 16::{index + 1}",
            }
        )
    return result


def scale_port_rows(nb: Ovsdb) -> list[dict[str, Any]]:
    return nb.find(
        "Logical_Switch_Port",
        f"{OWNER}{json.dumps(f'self-scale-ports:{SCALE_CHASSIS}')}",
        columns=("_uuid", "name", "addresses", "port_security"),
    )


def assert_scale_ports(
    runner: Runner,
    nb: Ovsdb,
    sb: Ovsdb,
    count: int,
    snapshots: Optional[Snapshots] = None,
) -> None:
    timeout = scale_chassis_sync(runner)
    expected = scale_ports(count)
    rows = {row["name"]: row for row in scale_port_rows(nb)}
    assert set(rows) == {port["name"] for port in expected}

    for port in expected:
        row = rows[port["name"]]
        assert row["addresses"] == port["addresses"]
        assert row["port_security"] == port["addresses"]
        assert nb.referring_names("Logical_Switch", "ports", row["_uuid"]) == [
            port["switch"]
        ]
        chassis = sb.by_name("Chassis", port["chassis"], "_uuid")
        runner.wait(
            "ovn-sbctl",
            "--bare",
            "--columns=chassis",
            "find",
            "Port_Binding",
            f"logical_port={port['name']}",
            attempts=timeout * 5,
            interval=0.2,
            until=lambda result, uuid=chassis["_uuid"]: uuid in result.stdout,
        )
        assert (
            sb.one(
                "Port_Binding",
                f"logical_port={port['name']}",
                columns=("chassis",),
            )["chassis"]
            == chassis["_uuid"]
        )

        assert (
            runner.output(
                "ovs-vsctl",
                "port-to-br",
                port["interface"],
            )
            == "br-int"
        )
        assert (
            runner.output(
                "ovs-vsctl",
                "get",
                "Interface",
                port["interface"],
                "external_ids:iface-id",
            ).strip('"')
            == port["name"]
        )
        if snapshots:
            name = f"scale-port-{port['name']}"
            if snapshots.path(name).exists():
                assert row["_uuid"] == snapshots.load(name)
            else:
                snapshots.save(name, row["_uuid"])


def assert_scale_port_absent(runner: Runner, nb: Ovsdb, sb: Ovsdb, index: int) -> None:
    name = f"ovn-scale-pod-{index}"
    interface = f"osp{index:08x}"
    timeout = read_int(os.environ, "OTT_SCALE_CHASSIS_TIMEOUT", 120)

    assert not nb.exists("Logical_Switch_Port", f"name={name}")
    runner.wait(
        "ovn-sbctl",
        "--bare",
        "--columns=_uuid",
        "find",
        "Port_Binding",
        f"logical_port={name}",
        attempts=timeout * 5,
        interval=0.2,
        until=lambda result: not result.stdout.strip(),
    )
    assert not runner.succeeds(
        "ovs-vsctl",
        "port-to-br",
        interface,
    )


class TestPreconditions:
    def test_northbound_database_is_available(self) -> None:
        assert Runner().succeeds("ovn-nbctl", "show")


class TestInitial:
    def test_three_ports_are_bound(
        self, runner: Runner, nb: Ovsdb, sb: Ovsdb, snapshots: Snapshots
    ) -> None:
        assert_scale_ports(runner, nb, sb, 3, snapshots)


class TestReapplied:
    def test_reapply_preserves_three_bound_ports(
        self, runner: Runner, nb: Ovsdb, sb: Ovsdb, snapshots: Snapshots
    ) -> None:
        assert_scale_ports(runner, nb, sb, 3, snapshots)


class TestContracted:
    def test_two_ports_remain_bound(
        self, runner: Runner, nb: Ovsdb, sb: Ovsdb, snapshots: Snapshots
    ) -> None:
        assert_scale_ports(runner, nb, sb, 2, snapshots)

    def test_removed_port_leaves_no_stale_state(
        self, runner: Runner, nb: Ovsdb, sb: Ovsdb
    ) -> None:
        assert_scale_port_absent(runner, nb, sb, 2)


class TestResult:
    def test_two_ports_remain_bound(
        self, runner: Runner, nb: Ovsdb, sb: Ovsdb, snapshots: Snapshots
    ) -> None:
        assert_scale_ports(runner, nb, sb, 2, snapshots)

    def test_removed_port_remains_absent(
        self, runner: Runner, nb: Ovsdb, sb: Ovsdb
    ) -> None:
        assert_scale_port_absent(runner, nb, sb, 2)
