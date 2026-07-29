import importlib.util
import time

import pytest


def load(tree, name, path):
    spec = importlib.util.spec_from_file_location(name, tree / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def configuration(**overrides):
    return {
        "id": "contract",
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


def port_configuration(**overrides):
    return {
        "id": "contract-ports",
        "port_count": 3,
        "start_index": 10,
        "port_prefix": "pod",
        "interface_prefix": "sp",
        "chassis": "worker-7",
        "network_index": 7,
        "switch_prefix": "lswitch",
        "switch": "",
        "bridge": "br-int",
        "ports": [],
        "ipv4": True,
        "ipv6": True,
        "internal_ipv4": "10.0.0.0/24",
        "internal_ipv6": "fd10::/80",
        "mtu": 0,
        "nbctl": ["ovn-nbctl", "--db=tcp:central:6641"],
        "ovs_vsctl": ["ovs-vsctl"],
        **overrides,
    }


def test_generates_arbitrary_worker_count(tree):
    topology = load(
        tree,
        "scale_topology",
        "roles/ovn_scale_topology/files/generate.py",
    ).generate(configuration())

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


def test_assigns_logical_workers_to_provisioned_chassis(tree):
    topology = load(
        tree,
        "scale_topology_chassis",
        "roles/ovn_scale_topology/files/generate.py",
    ).generate(configuration(worker_count=3, chassis=["compute-1", "compute-2"]))

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
    assert all(
        "snat-ct-zone" not in router["options"]
        for router in topology["routers"]
        if router["name"].startswith("gwrouter-")
    )


def test_rejects_exhausted_chassis_vlan_space(tree):
    generate = load(
        tree,
        "scale_topology_vlan_limit",
        "roles/ovn_scale_topology/files/generate.py",
    ).generate

    with pytest.raises(ValueError, match="external VLAN space"):
        generate(configuration(worker_count=4095, chassis=["compute-1"]))


def test_configures_requested_snat_conntrack_zone(tree):
    topology = load(
        tree,
        "scale_topology_snat_zone",
        "roles/ovn_scale_topology/files/generate.py",
    ).generate(configuration(worker_count=2, snat_ct_zone=42))

    assert [
        router["options"]["snat-ct-zone"]
        for router in topology["routers"]
        if router["name"].startswith("gwrouter-")
    ] == [42, 42]


def test_generates_scale_ports_for_current_chassis(tree):
    ports = load(
        tree,
        "scale_ports",
        "roles/ovn_scale_ports/files/generate.py",
    ).generate(port_configuration())

    assert ports["owner"] == "contract-ports:worker-7"
    assert [port["chassis"] for port in ports["ports"]] == ["worker-7"] * 3
    assert [port["addresses"] for port in ports["ports"]] == [
        "02:0a:00:00:00:0a 10.0.7.1 fd10::7:0:0:1",
        "02:0a:00:00:00:0b 10.0.7.2 fd10::7:0:0:2",
        "02:0a:00:00:00:0c 10.0.7.3 fd10::7:0:0:3",
    ]
    assert ports["southbound"]["ports"] == ["pod-10", "pod-11", "pod-12"]
    assert all("container" not in port for port in ports["ports"])


def test_accepts_explicit_local_scale_ports(tree):
    ports = load(
        tree,
        "explicit_scale_ports",
        "roles/ovn_scale_ports/files/generate.py",
    ).generate(
        port_configuration(
            port_count=0,
            ports=[
                {},
                {
                    "name": "special-port",
                    "interface": "special0",
                    "switch": "special-switch",
                    "bridge": "br-special",
                    "mac": "02:00:00:00:00:ff",
                    "addresses": "02:00:00:00:00:ff 192.0.2.1",
                    "mtu": 1400,
                },
            ],
        )
    )

    assert [port["chassis"] for port in ports["ports"]] == [
        "worker-7",
        "worker-7",
    ]
    assert ports["ports"][1] == {
        "name": "special-port",
        "interface": "special0",
        "switch": "special-switch",
        "chassis": "worker-7",
        "bridge": "br-special",
        "mac": "02:00:00:00:00:ff",
        "addresses": "02:00:00:00:00:ff 192.0.2.1",
        "mtu": 1400,
    }


def test_scale_port_cleanup_batches_a_valid_ovs_command(tree, monkeypatch):
    apply = load(
        tree,
        "scale_ports_cleanup",
        "roles/ovn_scale_ports/files/apply.py",
    )
    captured = []
    monkeypatch.setattr(
        apply,
        "_rows",
        lambda command, table, *columns: (
            []
            if table == "Bridge"
            else [
                {
                    "_uuid": "old-uuid",
                    "name": "old-interface",
                    "external_ids": {"ovn-tmt-tests-owner": "contract-ports"},
                }
            ]
        ),
    )
    monkeypatch.setattr(
        apply,
        "_batch",
        lambda command, groups: captured.extend(groups),
    )

    apply._configure_ovs(
        {
            "owner": "contract-ports",
            "ovs_vsctl": ["ovs-vsctl"],
            "ports": [],
        }
    )

    assert captured == [[["--if-exists", "del-port", "old-interface"]]]


def test_explicit_worker_names_override_generation(tree):
    topology = load(
        tree,
        "scale_topology",
        "roles/ovn_scale_topology/files/generate.py",
    ).generate(configuration(worker_count=500, workers=["alpha", "beta"]))

    assert [worker["name"] for worker in topology["workers"]] == ["alpha", "beta"]


def test_records_removed_southbound_objects(tree):
    topology = {
        "owner": "contract",
        "southbound": {
            "datapaths": ["kept-switch", "kept-router"],
            "ports": ["kept-port"],
        },
    }
    state = {
        "switches": [
            {
                "name": name,
                "external_ids": {"ovn-tmt-tests-owner": "contract"},
            }
            for name in ("kept-switch", "old-switch")
        ],
        "routers": [
            {
                "name": name,
                "external_ids": {"ovn-tmt-tests-owner": "contract"},
            }
            for name in ("kept-router", "old-router")
        ],
        "switch_ports": [
            {
                "name": name,
                "external_ids": {"ovn-tmt-tests-owner": "contract"},
            }
            for name in ("kept-port", "old-port")
        ],
    }
    apply = load(
        tree,
        "scale_topology_apply",
        "roles/ovn_scale_topology/files/apply.py",
    )

    apply._record_removed(topology, state)

    assert topology["southbound"]["absent_datapaths"] == [
        "old-router",
        "old-switch",
    ]
    assert topology["southbound"]["absent_ports"] == ["old-port"]


def test_apply_records_convergence_start_before_changes(tree, monkeypatch, capsys):
    topology = {
        "owner": "contract",
        "southbound": {},
        "workers": [],
        "switches": [],
        "routers": [],
    }
    apply = load(
        tree,
        "scale_topology_apply_start",
        "roles/ovn_scale_topology/files/apply.py",
    )
    monkeypatch.setattr(apply, "_configure_roots", lambda *_: None)
    monkeypatch.setattr(apply, "_rows", lambda *_: [])
    for name in (
        "_configure_ports",
        "_configure_gateway_chassis",
        "_configure_routes",
        "_configure_nat",
        "_record_removed",
        "_cleanup",
    ):
        monkeypatch.setattr(apply, name, lambda *_: None)

    before = time.monotonic_ns()
    apply.apply(topology)
    after = time.monotonic_ns()
    capsys.readouterr()

    assert before <= topology["southbound"]["started_ns"] <= after


def test_southbound_checker_rejects_missing_and_stale_objects(tree):
    checker = load(
        tree,
        "southbound_convergence",
        "roles/ovn_sb_convergence/files/check.py",
    )
    expected = {
        "datapaths": ["present", "missing"],
        "ports": ["present-port"],
        "absent_datapaths": ["stale"],
        "absent_ports": [],
    }

    with pytest.raises(RuntimeError, match="missing_datapaths.*stale_datapaths"):
        checker.verify(
            expected,
            {"datapaths": {"present", "stale"}, "ports": {"present-port"}},
        )
