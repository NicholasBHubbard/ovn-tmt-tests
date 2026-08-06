import runpy
from pathlib import Path
from typing import Any

import pytest
from ovn_test.namespace import OvnNamespace
from self._support import FakeRunner, contains


def cluster_density_config() -> dict[str, Any]:
    return {
        "startup": 1,
        "total": 2,
        "build_pods": 6,
        "test_pods": 4,
        "protocols": ["tcp", "udp", "sctp"],
        "timeout": 60,
        "ipv4": True,
        "ipv6": False,
        "mtu": 576,
        "chassis": 2,
        "workers": 2,
        "base_pods": 10,
    }


def test_cluster_density_reproduces_original_workload_shape(tree: Path) -> None:
    module = runpy.run_path(
        str(tree / "tests/ovn-scale-testing/cluster-density/test.py")
    )
    runner = FakeRunner()
    namespace = OvnNamespace(
        runner,
        "cluster-density",
        "NS_density_0",
        0,
    )
    endpoints = [
        {
            "port": f"pod-{index}",
            "ipv4": f"10.0.0.{index}",
            "ipv6": f"fd10::{index}",
        }
        for index in range(1, 6)
    ]

    namespace.create()
    namespace.add_endpoints(endpoints)
    module["add_namespace_services"](
        namespace,
        endpoints,
        ["tcp", "udp", "sctp"],
        "group-uuid",
    )

    commands = [call[1] for call in runner.calls]
    assert (
        len(
            [
                command
                for command in commands
                if command[:3] == ("ovn-nbctl", "create", "Port_Group")
            ]
        )
        == 3
    )
    assert (
        len(
            [
                command
                for command in commands
                if command[:3] == ("ovn-nbctl", "create", "Address_Set")
            ]
        )
        == 2
    )
    load_balancers = [
        command for command in commands if contains(command, "create", "Load_Balancer")
    ]
    assert len(load_balancers) == 3
    tcp = next(command for command in load_balancers if "protocol=tcp" in command)
    assert 'vips:"30.1.0.1:80"="10.0.0.1:8080,10.0.0.2:8080"' in tcp
    assert 'vips:"30.1.0.2:80"="10.0.0.3:8080"' in tcp
    assert 'vips:"30.1.0.3:80"="10.0.0.4:8080,10.0.0.5:8080"' in tcp
    assert 'vips:"[30:1::1]:80"="[fd10::1]:8080,[fd10::2]:8080"' in tcp
    assert contains(
        tcp,
        "add",
        "Load_Balancer_Group",
        "group-uuid",
        "load_balancer",
        "@lb",
    )

    namespace.cleanup()
    namespace.verify_cleanup()


def test_cluster_density_honors_service_configuration(tree: Path) -> None:
    module = runpy.run_path(
        str(tree / "tests/ovn-scale-testing/cluster-density/test.py")
    )
    runner = FakeRunner()
    namespace = OvnNamespace(runner, "owner", "services", 0, ipv6=False)
    endpoints = [
        {"port": f"pod-{index}", "ipv4": f"10.0.0.{index}"} for index in range(1, 5)
    ]
    namespace.create()
    runner.calls.clear()

    module["add_namespace_services"](
        namespace,
        endpoints,
        ["tcp"],
        "group",
        ipv4_vip_network="192.0.2.0/24",
        vip_port=443,
        backend_port=8443,
    )

    command = next(
        call[1] for call in runner.calls if contains(call[1], "create", "Load_Balancer")
    )
    assert 'vips:"192.0.3.1:443"="10.0.0.1:8443,10.0.0.2:8443"' in command
    assert 'vips:"192.0.3.2:443"="10.0.0.3:8443"' in command
    assert 'vips:"192.0.3.3:443"="10.0.0.4:8443"' in command


@pytest.mark.parametrize(
    ("options", "message"),
    (
        ({"endpoints": []}, "four endpoints"),
        ({"endpoints": ["pod"] * 4}, "must be a mapping"),
        ({"protocols": "tcp"}, "non-empty sequence"),
        ({"protocols": ["tcp", "tcp"]}, "unique"),
        ({"protocols": ["http"]}, "tcp, udp or sctp"),
        ({"ipv4_vip_network": "2001:db8::/64"}, "must be IPv4"),
        ({"vip_port": 0}, "port"),
    ),
)
def test_cluster_density_rejects_invalid_service_configuration(
    tree: Path,
    options: dict[str, Any],
    message: str,
) -> None:
    module = runpy.run_path(
        str(tree / "tests/ovn-scale-testing/cluster-density/test.py")
    )
    runner = FakeRunner()
    namespace = OvnNamespace(runner, "owner", "services", 0, ipv6=False)
    namespace.create()
    runner.calls.clear()
    values: dict[str, Any] = {
        "namespace": namespace,
        "endpoints": [
            {"port": f"pod-{index}", "ipv4": f"10.0.0.{index}"} for index in range(1, 5)
        ],
        "protocols": ["tcp"],
        "group": "group",
    }
    values.update(options)

    with pytest.raises(ValueError, match=message):
        module["add_namespace_services"](**values)
    assert not any("Load_Balancer" in call[1] for call in runner.calls)


@pytest.mark.parametrize(
    "values",
    (
        {"startup": -1},
        {"startup": 3, "total": 2},
        {"total": 0},
        {"build_pods": -1},
        {"test_pods": 3},
        {"protocols": []},
        {"protocols": "tcp"},
        {"protocols": [1]},
        {"protocols": ["tcp", "tcp"]},
        {"protocols": ["tcp", "http"]},
        {"timeout": 0},
        {"ipv4": False, "ipv6": False},
        {"ipv4": "true"},
        {"ipv6": False, "mtu": 575},
        {"mtu": 65536},
        {"mtu": 1342.0},
        {"total": True},
        {"chassis": 1},
        {"workers": 0},
        {"base_pods": -1},
        {"startup": 0, "total": 65535, "build_pods": 0},
        {"ipv4_vip_network": "2001:db8::/64"},
        {"ipv4_vip_network": "255.255.254.0/24"},
        {"vip_port": 0},
        {"backend_port": 65536},
    ),
)
def test_cluster_density_rejects_invalid_configuration(
    tree: Path,
    values: dict[str, Any],
) -> None:
    module = runpy.run_path(
        str(tree / "tests/ovn-scale-testing/cluster-density/test.py")
    )
    config = cluster_density_config()
    config.update(values)

    with pytest.raises(ValueError, match=r".+"):
        module["validate_cluster_density"](**config)


def test_cluster_density_accepts_original_defaults(tree: Path) -> None:
    module = runpy.run_path(
        str(tree / "tests/ovn-scale-testing/cluster-density/test.py")
    )
    module["validate_cluster_density"](
        startup=3800,
        total=4000,
        build_pods=6,
        test_pods=4,
        protocols=["tcp", "udp", "sctp"],
        timeout=60,
        ipv4=True,
        ipv6=False,
        mtu=1342,
        chassis=2,
        workers=250,
        base_pods=10,
    )
