import runpy
from pathlib import Path
from typing import Any

import pytest
from ovn_test.workload import Workload
from self._support import FakeRunner, contains


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


def test_service_route_load_balancer_replacement(tree: Path, tmp_path: Path) -> None:
    runner = FakeRunner()
    topology = {
        "load_balancer_group": "cluster-lb-group",
        "workers": [
            {
                "name": "worker-0",
                "chassis": "compute-1",
                "switch": "switch-0",
                "gateway_router": "gwrouter-worker-0",
                "internal": {"ipv4": "10.0.0.0/24", "ipv6": "fd10::/80"},
                "external": {"ipv4": "172.16.0.0/24", "ipv6": "fd20::/80"},
            },
            {
                "name": "worker-1",
                "chassis": "compute-2",
                "switch": "switch-1",
                "gateway_router": "gwrouter-worker-1",
                "internal": {
                    "ipv4": "10.0.1.0/24",
                    "ipv6": "fd10:0:0:1::/80",
                },
                "external": {
                    "ipv4": "172.16.1.0/24",
                    "ipv6": "fd20:0:0:1::/80",
                },
            },
        ],
    }
    workload = Workload(
        runner,
        ["compute-1", "compute-2"],
        "service-route",
        "sr",
        tmp_path / "metrics.csv",
        scale_topology=topology,
    )
    service_route = runpy.run_path(
        str(tree / "tests/ovn-scale-testing/service-route/test.py")
    )
    endpoints = [workload.endpoint(index) for index in range(3)]

    workload.create_namespace()
    service_route["add_service_routes"](workload, 0, endpoints, ["tcp"])
    service_route["add_service_routes"](workload, 0, endpoints, ["tcp"])

    commands = [call[1] for call in runner.calls]
    created = [
        command for command in commands if contains(command, "create", "Load_Balancer")
    ]
    assert len(created) == 6
    assert len(workload.load_balancers) == 6
    cluster = next(
        command for command in created if 'name="slb-cluster-0-tcp"' in command
    )
    assert 'vips:"90.0.0.1:80"="10.0.1.1:8080,10.0.0.2:8080"' in cluster
    assert contains(
        cluster,
        "add",
        "Load_Balancer_Group",
        "load-balancer-group-uuid",
        "load_balancer",
        "@lb",
    )
    node = next(
        command for command in created if 'name="slb-node-0-worker-0-tcp"' in command
    )
    assert 'vips:"172.16.0.254:80"="10.0.1.1:8080,10.0.0.2:8080"' in node
    assert contains(
        node,
        "add",
        "Logical_Switch",
        "switch-0",
        "load_balancer",
        "@lb",
    )
    assert contains(
        node,
        "add",
        "Logical_Router",
        "gwrouter-worker-0",
        "load_balancer",
        "@lb",
    )
    assert any(
        'name="slb6-cluster-0-tcp"' in command
        and 'vips:"[9::1]:80"="[fd10:0:0:1::1]:8080,[fd10::2]:8080"' in command
        for command in created
    )

    workload.cleanup()
    workload.verify_cleanup()
