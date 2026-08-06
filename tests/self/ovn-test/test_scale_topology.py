import time
from typing import Any
from unittest.mock import Mock

import ovn_test.scale_topology as topology_module
import pytest
from ovn_test.command import Runner
from ovn_test.scale_topology import ScaleTopology, configuration, generate


def topology_configuration(**overrides: Any) -> dict[str, Any]:
    return {
        "id": "self-test",
        "worker_count": 500,
        "worker_prefix": "worker",
        "workers": [],
        "chassis": [],
        "ipv4": True,
        "ipv6": True,
        "internal_ipv4": "10.0.0.0/24",
        "internal_ipv6": "fd10::/80",
        "external_ipv4": "172.16.0.0/24",
        "external_ipv6": "fd20::/80",
        "join_ipv4": "192.168.0.0/16",
        "join_ipv6": "fd30::/64",
        "cluster_ipv4": "10.0.0.0/8",
        "cluster_ipv6": "fd10::/48",
        "cluster_router": "cluster",
        "join_switch": "join",
        "load_balancer_group": "cluster-lb-group",
        "snat_ct_zone": "",
        "physical_network": "provider",
        "physical_bridge": "br-provider",
        **overrides,
    }


def test_generates_arbitrary_worker_count() -> None:
    topology = generate(topology_configuration())

    assert len(topology["workers"]) == 500
    assert len(topology["switches"]) == 1001
    assert len(topology["routers"]) == 501
    assert len(topology["router_ports"]) == 1501
    assert len(topology["southbound"]["datapaths"]) == 1502
    assert len(topology["southbound"]["ports"]) == 2001
    assert topology["workers"][-1]["name"] == "worker-499"
    assert topology["workers"][-1]["chassis"] == "worker-499"
    assert topology["workers"][-1]["internal"]["ipv4"] == "10.1.243.0/24"
    assert topology["physical_network"] == "provider"
    assert topology["physical_bridge"] == "br-provider"


def test_assigns_logical_workers_to_provisioned_chassis() -> None:
    topology = generate(
        topology_configuration(worker_count=3, chassis=["compute-1", "compute-2"])
    )

    assert [worker["chassis"] for worker in topology["workers"]] == [
        "compute-1",
        "compute-2",
        "compute-1",
    ]
    assert [
        router["options"]["chassis"]
        for router in topology["routers"]
        if router["name"].startswith("gwrouter-")
    ] == ["compute-1", "compute-2", "compute-1"]
    assert [item["chassis"] for item in topology["gateway_chassis"]] == [
        "compute-1",
        "compute-2",
        "compute-1",
    ]
    assert [worker.get("external_vlan") for worker in topology["workers"]] == [
        1,
        None,
        2,
    ]
    assert [port.get("tag") for port in topology["localnet_ports"]] == [1, None, 2]


def test_rejects_exhausted_chassis_vlan_space() -> None:
    with pytest.raises(ValueError, match="external VLAN space"):
        generate(topology_configuration(worker_count=4095, chassis=["compute-1"]))


def test_configures_requested_snat_conntrack_zone() -> None:
    topology = generate(topology_configuration(worker_count=2, snat_ct_zone=42))

    assert [
        router["options"]["snat-ct-zone"]
        for router in topology["routers"]
        if router["name"].startswith("gwrouter-")
    ] == [42, 42]


def test_explicit_worker_names_override_generation() -> None:
    topology = generate(
        topology_configuration(worker_count=500, workers=["alpha", "beta"])
    )

    assert [worker["name"] for worker in topology["workers"]] == ["alpha", "beta"]


def test_generates_ipv6_networks_starting_at_zero() -> None:
    topology = generate(
        topology_configuration(
            worker_count=1,
            ipv4=False,
            internal_ipv6="::/120",
            external_ipv6="1::/120",
            join_ipv6="2::/120",
            cluster_ipv6="::/0",
        )
    )

    assert topology["workers"][0]["internal"]["ipv6"] == "::/120"


@pytest.mark.parametrize(
    ("overrides", "message"),
    (
        ({"worker_count": True}, "worker_count"),
        ({"worker_count": "2"}, "worker_count"),
        ({"workers": "worker"}, "workers"),
        ({"workers": ["worker", "worker"]}, "unique"),
        ({"chassis": ["compute", "compute"]}, "chassis"),
        ({"ipv4": 1}, "booleans"),
        ({"internal_ipv4": "fd00::/64"}, "internal_ipv4"),
        ({"external_ipv4": "192.0.2.1"}, "external_ipv4"),
        ({"join_ipv4": "192.0.2.0/31", "workers": ["one"]}, "too small"),
        ({"snat_ct_zone": True}, "snat_ct_zone"),
        ({"cluster_router": ""}, "cluster_router"),
        ({"join_switch": "lswitch-worker-0"}, "logical switch names"),
    ),
)
def test_rejects_invalid_topology_configuration(
    overrides: dict[str, Any], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        generate(topology_configuration(**overrides))


def test_rejects_empty_explicit_worker_name() -> None:
    with pytest.raises(ValueError, match="empty name"):
        configuration([], {"OTT_SCALE_WORKER_NAMES": "worker-1,,worker-2"})


@pytest.mark.parametrize(
    ("options", "message"),
    (
        ({"timeout": True}, "timeout"),
        ({"wait": "yes"}, "wait"),
    ),
)
def test_scale_topology_rejects_invalid_lifecycle_options(
    options: dict[str, Any], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        ScaleTopology(Mock(spec=Runner), topology_configuration(), **options)


def test_options_preserve_strings_and_normalize_booleans() -> None:
    commands = topology_module._options(
        "Logical_Router",
        "router",
        "options",
        {"chassis": "Compute-A", "enabled": False},
    )

    assert 'options:chassis="Compute-A"' in commands[1]
    assert 'options:enabled="false"' in commands[2]


def test_rejects_foreign_and_duplicate_named_objects() -> None:
    foreign = [{"name": "switch", "external_ids": {}}]
    duplicates = [
        {"name": "switch", "external_ids": {topology_module.OWNER: "self-test"}},
        {"name": "switch", "external_ids": {topology_module.OWNER: "self-test"}},
    ]

    with pytest.raises(RuntimeError, match="not owned"):
        topology_module._reject_collisions(
            foreign, ["switch"], "self-test", "logical switch"
        )
    with pytest.raises(RuntimeError, match="not unique"):
        topology_module._reject_collisions(
            duplicates, ["switch"], "self-test", "logical switch"
        )


def test_move_reference_only_changes_parent_when_needed() -> None:
    commands: list[list[Any]] = []

    topology_module._move_reference(
        commands, "Logical_Router", "old", "old", "ports", "uuid"
    )
    topology_module._move_reference(
        commands, "Logical_Router", "old", "new", "ports", "uuid"
    )

    assert commands == [
        ["remove", "Logical_Router", "old", "ports", "uuid"],
        ["add", "Logical_Router", "new", "ports", "uuid"],
    ]


def test_rejects_unowned_load_balancer_group(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = Mock()

    def rows(table: str, *columns: str) -> list[dict[str, Any]]:
        del columns
        if table == "NB_Global":
            return [{"external_ids": {}}]
        return [{"_uuid": "group-uuid", "name": "group"}]

    database.rows.side_effect = rows
    monkeypatch.setattr(topology_module, "_Database", lambda _runner: database)

    with pytest.raises(RuntimeError, match="not owned"):
        topology_module._apply_load_balancer_group(
            Mock(spec=Runner), "group", [], [], "self-test"
        )

    database.batch.assert_not_called()


def test_new_load_balancer_group_records_ownership(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = Mock()
    database.rows.side_effect = lambda table, *_columns: (
        [{"external_ids": {}}] if table == "NB_Global" else []
    )
    monkeypatch.setattr(topology_module, "_Database", lambda _runner: database)

    topology_module._apply_load_balancer_group(
        Mock(spec=Runner), "group", ["switch"], ["router"], "self-test"
    )

    commands = database.batch.call_args.args[0][0]
    owner_key = topology_module._group_owner_key("group")
    assert [
        "set",
        "NB_Global",
        ".",
        f'external_ids:{owner_key}="self-test"',
    ] in commands


def test_records_removed_southbound_objects() -> None:
    topology = {
        "owner": "self-test",
        "southbound": {
            "datapaths": ["kept-switch", "kept-router"],
            "ports": ["kept-port"],
        },
    }
    state = {
        "switches": [
            {
                "name": name,
                "external_ids": {topology_module.OWNER: "self-test"},
            }
            for name in ("kept-switch", "old-switch")
        ],
        "routers": [
            {
                "name": name,
                "external_ids": {topology_module.OWNER: "self-test"},
            }
            for name in ("kept-router", "old-router")
        ],
        "switch_ports": [
            {
                "name": name,
                "external_ids": {topology_module.OWNER: "self-test"},
            }
            for name in ("kept-port", "old-port")
        ],
    }
    topology_module._record_removed(topology, state)

    assert topology["southbound"]["absent_datapaths"] == [
        "old-router",
        "old-switch",
    ]
    assert topology["southbound"]["absent_ports"] == ["old-port"]


def test_apply_records_convergence_start_before_changes(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    topology = {
        "owner": "self-test",
        "southbound": {},
        "workers": [],
        "switches": [],
        "routers": [],
        "router_ports": [],
        "localnet_ports": [],
        "gateway_chassis": [],
    }
    monkeypatch.setattr(topology_module, "_configure_roots", lambda *_: None)
    monkeypatch.setattr(topology_module._Database, "rows", lambda *_: [])
    for name in (
        "_configure_ports",
        "_configure_gateway_chassis",
        "_configure_routes",
        "_configure_nat",
        "_record_removed",
        "_cleanup",
    ):
        monkeypatch.setattr(topology_module, name, lambda *_: None)

    before = time.monotonic_ns()
    topology_module._apply_database(Mock(spec=Runner), topology)
    after = time.monotonic_ns()
    capsys.readouterr()

    assert before <= topology["southbound"]["started_ns"] <= after


def test_cleanup_attempts_database_group_and_convergence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_error = RuntimeError("database cleanup failed")
    group = Mock(side_effect=RuntimeError("group cleanup failed"))
    monkeypatch.setattr(
        topology_module, "_apply_database", Mock(side_effect=database_error)
    )
    monkeypatch.setattr(topology_module, "_apply_load_balancer_group", group)
    empty = {
        "owner": "self-test",
        "workers": [],
        "load_balancer_group": "group",
    }

    with pytest.raises(RuntimeError, match="database cleanup failed") as error:
        topology_module._apply(Mock(spec=Runner), empty)

    assert error.value is database_error
    group.assert_called_once()

    topology = ScaleTopology(Mock(spec=Runner), topology_configuration())
    topology.data = {
        "owner": "self-test",
        "load_balancer_group": "group",
    }
    converge = Mock(side_effect=RuntimeError("convergence failed"))
    monkeypatch.setattr(topology, "_converge", converge)
    monkeypatch.setattr(topology_module, "_apply", Mock(side_effect=database_error))

    with pytest.raises(RuntimeError, match="database cleanup failed") as error:
        topology.cleanup()

    assert error.value is database_error
    converge.assert_called_once()
    assert topology.data is not None
