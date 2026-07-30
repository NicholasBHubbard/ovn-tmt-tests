import runpy
from pathlib import Path

import pytest


def test_dpdk_version_line_need_not_be_first(tree: Path) -> None:
    workload = runpy.run_path(str(tree / "tests/build/dpdk/test.py"))

    assert workload["supports_dpdk"](
        "ovs-vswitchd (Open vSwitch) 3.6.0\nDPDK 24.11.1\n"
    )
    assert not workload["supports_dpdk"]("ovs-vswitchd (Open vSwitch) 3.6.0\n")


def test_np_multitenant_reproduces_original_workload_shape(tree: Path) -> None:
    workload = runpy.run_path(str(tree / "tests/scale/np-multitenant/test.py"))
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
    workload = runpy.run_path(str(tree / "tests/scale/np-multitenant/test.py"))
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
