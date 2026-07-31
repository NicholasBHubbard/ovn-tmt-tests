from pathlib import Path
from typing import Any

import pytest

from ._support import load_module


def port_configuration(**overrides: Any) -> dict[str, Any]:
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


def test_generates_scale_ports_for_current_chassis(tree: Path) -> None:
    ports = load_module(
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


def test_accepts_explicit_local_scale_ports(tree: Path) -> None:
    ports = load_module(
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


def test_scale_port_cleanup_batches_a_valid_ovs_command(
    tree: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    apply = load_module(
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
