import runpy
from pathlib import Path
from typing import Any

import pytest


def np_labels_config(mode: str = "small") -> dict[str, Any]:
    return {
        "mode": mode,
        "namespaces": 2,
        "pods_per_namespace": 16,
        "labels": 4,
        "base_pods": 2,
        "protocols": ["tcp", "udp", "sctp"],
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


def service_route_config() -> dict[str, Any]:
    return {
        "iterations": 16,
        "backends": 4,
        "base_pods": 2,
        "protocols": ["tcp", "udp", "sctp"],
        "timeout": 60,
        "sync_timeout": 1800,
        "ipv4": True,
        "ipv6": True,
        "mtu": 1342,
        "workers": 2,
        "chassis": 2,
    }


def test_np_multitenant_reproduces_original_workload_shape(tree: Path) -> None:
    workload = runpy.run_path(
        str(tree / "tests/ovn-scale-testing/np-multitenant/test.py")
    )
    ranges = workload["parse_ranges"]("200:5,480:20,495:100")
    config = {
        "namespaces": 500,
        "ranges": ranges,
        "base_pods": 10,
        "small_external_count": 3,
        "large_external_count": 20,
        "protocols": ["tcp", "udp", "sctp"],
        "timeout": 60,
        "sync_timeout": 1800,
        "ipv4": True,
        "ipv6": False,
        "mtu": 1342,
        "workers": 250,
        "chassis": 2,
        "deny_priority": 1,
        "control_priority": 2,
        "allow_priority": 3,
    }

    workload["validate_config"](config)

    assert workload["pods_in_namespace"](199, ranges) == 1
    assert workload["pods_in_namespace"](200, ranges) == 5
    assert workload["pods_in_namespace"](480, ranges) == 20
    assert workload["pods_in_namespace"](495, ranges) == 100
    assert config["total_pods"] == 2400
    assert workload["address_range"]("42.42.42.1", 3, 4) == [
        "42.42.42.1",
        "42.42.42.2",
        "42.42.42.3",
    ]
    assert workload["address_range"]("::1", 3, 6) == ["::1", "::2", "::3"]


@pytest.mark.parametrize(
    "ranges",
    (
        "bad",
        "1:0",
        "1:2,1:3",
        "2:1",
        "1:2,",
    ),
)
def test_np_multitenant_rejects_invalid_ranges(tree: Path, ranges: str) -> None:
    workload = runpy.run_path(
        str(tree / "tests/ovn-scale-testing/np-multitenant/test.py")
    )
    config = {
        "namespaces": 2,
        "base_pods": 0,
        "small_external_count": 1,
        "large_external_count": 0,
        "protocols": ["tcp"],
        "timeout": 1,
        "sync_timeout": 1,
        "ipv4": True,
        "ipv6": False,
        "mtu": 576,
        "workers": 2,
        "chassis": 2,
        "deny_priority": 1,
        "control_priority": 2,
        "allow_priority": 3,
    }

    def validate() -> None:
        config["ranges"] = workload["parse_ranges"](ranges)
        workload["validate_config"](config)

    with pytest.raises(ValueError, match=r"(?i)range"):
        validate()


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


@pytest.mark.parametrize("mode", ("small", "large"))
def test_np_labels_reproduces_original_workload_shape(tree: Path, mode: str) -> None:
    workload = runpy.run_path(str(tree / "tests/ovn-scale-testing/np-labels/test.py"))
    config = np_labels_config(mode)

    workload["validate_config"](config)
    groups = workload["label_groups"](config["total_pods"], config["labels"])

    assert config["total_pods"] == 32
    assert groups[0] == list(range(0, 32, 4))
    assert workload["local_label_index"](1, 2, 16, 4) == 18
    target = workload["target_indexes"](mode, 0, 0, 16, groups)
    if mode == "small":
        assert target == [2, 3, 6, 7, 10, 11, 14, 15]
    else:
        assert target == groups[1]


@pytest.mark.parametrize(
    ("name", "value"),
    (
        ("mode", "invalid"),
        ("namespaces", 0),
        ("pods_per_namespace", 3),
        ("labels", 2),
        ("base_pods", -1),
        ("protocols", []),
        ("ipv4", False),
        ("mtu", 575),
        ("allow_priority", 1),
    ),
)
def test_np_labels_rejects_invalid_configuration(
    tree: Path,
    name: str,
    value: Any,
) -> None:
    workload = runpy.run_path(str(tree / "tests/ovn-scale-testing/np-labels/test.py"))
    config = np_labels_config()
    config[name] = value

    with pytest.raises(ValueError, match=r".+"):
        workload["validate_config"](config)


def test_service_route_reproduces_original_workload_shape(tree: Path) -> None:
    workload = runpy.run_path(
        str(tree / "tests/ovn-scale-testing/service-route/test.py")
    )
    config = service_route_config()

    workload["validate_config"](config)

    assert config["total_pods"] == 80
    assert workload["cluster_vip"](0, 4) == "90.0.0.1"
    assert workload["cluster_vip"](15, 4) == "90.0.0.16"
    assert workload["cluster_vip"](0, 6) == "9::1"
    worker = {
        "name": "worker-0",
        "external": {"ipv4": "172.16.0.0/24", "ipv6": "fd20::/80"},
    }
    assert workload["worker_vip"](worker, 4) == "172.16.0.254"
    assert workload["worker_vip"](worker, 6) == "fd20::ffff:ffff:fffe"


@pytest.mark.parametrize(
    ("name", "value"),
    (
        ("iterations", 0),
        ("backends", 0),
        ("base_pods", -1),
        ("protocols", []),
        ("ipv4", "true"),
        ("mtu", 1279),
        ("workers", 0),
    ),
)
def test_service_route_rejects_invalid_configuration(
    tree: Path,
    name: str,
    value: Any,
) -> None:
    workload = runpy.run_path(
        str(tree / "tests/ovn-scale-testing/service-route/test.py")
    )
    config = service_route_config()
    config[name] = value

    with pytest.raises(ValueError, match=r".+"):
        workload["validate_config"](config)
