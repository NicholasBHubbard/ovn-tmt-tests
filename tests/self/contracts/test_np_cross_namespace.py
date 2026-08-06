import runpy
from pathlib import Path
from typing import Any

import pytest


def test_np_cross_namespace_reproduces_original_workload_shape(tree: Path) -> None:
    workload = runpy.run_path(
        str(tree / "tests/ovn-scale-testing/np-cross-namespace/test.py")
    )
    config = {
        "namespaces": 10,
        "pods_per_namespace": 5,
        "base_pods": 2,
        "protocols": ["tcp", "udp", "sctp"],
        "timeout": 60,
        "sync_timeout": 1800,
        "ipv4": True,
        "ipv6": True,
        "mtu": 1342,
        "workers": 2,
        "chassis": 2,
        "deny_priority": 1,
        "control_priority": 2,
        "allow_priority": 3,
    }

    workload["validate_config"](config)

    assert config["total_pods"] == 50


@pytest.mark.parametrize(
    ("name", "value"),
    (
        ("namespaces", 1),
        ("pods_per_namespace", 0),
        ("base_pods", -1),
        ("protocols", []),
        ("ipv4", False),
        ("mtu", 575),
        ("allow_priority", 1),
    ),
)
def test_np_cross_namespace_rejects_invalid_configuration(
    tree: Path,
    name: str,
    value: Any,
) -> None:
    workload = runpy.run_path(
        str(tree / "tests/ovn-scale-testing/np-cross-namespace/test.py")
    )
    config = {
        "namespaces": 10,
        "pods_per_namespace": 5,
        "base_pods": 2,
        "protocols": ["tcp"],
        "timeout": 60,
        "sync_timeout": 1800,
        "ipv4": True,
        "ipv6": False,
        "mtu": 1342,
        "workers": 2,
        "chassis": 2,
        "deny_priority": 1,
        "control_priority": 2,
        "allow_priority": 3,
    }
    config[name] = value

    with pytest.raises(ValueError, match=r".+"):
        workload["validate_config"](config)
