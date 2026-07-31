import subprocess
from typing import Any

import pytest
from ovn_test.namespace import OvnNamespace, validate_cluster_density

from ._support import FakeRunner, contains


def test_ovn_namespace_reproduces_cluster_density_state() -> None:
    runner = FakeRunner()
    namespace = OvnNamespace(
        runner,
        "cluster-density",
        "NS_density_0",
        0,
    )
    endpoints = [
        {
            "ipv4": f"10.0.0.{index}",
            "ipv6": f"fd10::{index}",
        }
        for index in range(1, 6)
    ]

    namespace.create()
    namespace.add_endpoints(endpoints)
    namespace.add_services(endpoints, ["tcp", "udp", "sctp"], "group-uuid")

    commands = [call[1] for call in runner.calls]
    assert len([command for command in commands if "pg-add" in command]) == 3
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
    assert namespace.cleaned


def test_ovn_namespace_manages_network_policy_state() -> None:
    runner = FakeRunner()
    namespace = OvnNamespace(
        runner,
        "network-policy",
        "NS_policy_0",
        0,
        ipv6=False,
    )
    endpoints = [
        {
            "port": f"pod-{index}",
            "ipv4": f"10.0.0.{index}",
        }
        for index in range(1, 3)
    ]

    namespace.create()
    namespace.add_endpoints(endpoints)
    assert not [call for call in runner.calls if "pg-set-ports" in call[1]]

    namespace.default_deny(4)
    namespace.allow_within(4)
    namespace.allow_external(
        ["42.42.42.1", "42.42.42.2"],
        name="trusted",
    )

    commands = [call[1] for call in runner.calls]
    for port_group in namespace.port_groups:
        assert (
            "ovn-nbctl",
            "pg-set-ports",
            port_group,
            "pod-1",
            "pod-2",
        ) in commands
    created_acls = [command for command in commands if "acl-add" in command]
    assert len(created_acls) == 7
    assert any(
        "ip4.src == $as_NS_policy_0 && outport == @pg_deny_igr_NS_policy_0" in command
        and "drop" in command
        for command in created_acls
    )
    assert any(
        "ip4.src == $as_NS_policy_0 && outport == @pg_NS_policy_0" in command
        and "allow-related" in command
        for command in created_acls
    )

    namespace.allow_external(["42.42.42.3"], name="trusted")
    assert (
        "ovn-nbctl",
        "--type=port-group",
        "acl-del",
        "pg_NS_policy_0",
        "to-lport",
        3,
        "ip4.src == {42.42.42.1,42.42.42.2} && outport == @pg_NS_policy_0",
    ) in [call[1] for call in runner.calls]
    assert (
        "ovn-nbctl",
        "--type=port-group",
        "--may-exist",
        "acl-add",
        "pg_NS_policy_0",
        "to-lport",
        3,
        "ip4.src == {42.42.42.3} && outport == @pg_NS_policy_0",
        "allow-related",
    ) in [call[1] for call in runner.calls]

    namespace.add_endpoints([{"port": "pod-3", "ipv4": "10.0.0.3"}])
    assert (
        "ovn-nbctl",
        "pg-set-ports",
        "pg_NS_policy_0",
        "pod-1",
        "pod-2",
        "pod-3",
    ) in [call[1] for call in runner.calls]

    namespace.cleanup()
    namespace.verify_cleanup()


def test_ovn_namespace_manages_ipv6_network_policy_state() -> None:
    runner = FakeRunner()
    namespace = OvnNamespace(
        runner,
        "network-policy",
        "NS_policy_6",
        6,
        ipv4=False,
    )

    namespace.create()
    namespace.add_endpoints([{"port": "pod-v6", "ipv6": "fd00::10"}])
    namespace.default_deny(6)
    namespace.allow_within(6)
    namespace.allow_external(
        ["2001:db8::1", "2001:db8::2"],
        family=6,
        name="trusted",
    )

    commands = [call[1] for call in runner.calls]
    assert any(
        command[:3] == ("ovn-nbctl", "add", "Address_Set")
        and command[-1] == '"fd00::10"'
        for command in commands
    )
    acls = {(command[-2], command[-1]) for command in commands if "acl-add" in command}
    assert acls == {
        (
            "ip6.src == $as6_NS_policy_6 && outport == @pg_deny_igr_NS_policy_6",
            "drop",
        ),
        (
            "outport == @pg_deny_igr_NS_policy_6 && nd",
            "allow",
        ),
        (
            "ip6.dst == $as6_NS_policy_6 && inport == @pg_deny_egr_NS_policy_6",
            "drop",
        ),
        (
            "inport == @pg_deny_egr_NS_policy_6 && nd",
            "allow",
        ),
        (
            "ip6.src == $as6_NS_policy_6 && outport == @pg_NS_policy_6",
            "allow-related",
        ),
        (
            "ip6.dst == $as6_NS_policy_6 && inport == @pg_NS_policy_6",
            "allow-related",
        ),
        (
            "ip6.src == {2001:db8::1,2001:db8::2} && outport == @pg_NS_policy_6",
            "allow-related",
        ),
    }

    namespace.cleanup()
    namespace.verify_cleanup()


@pytest.mark.parametrize(
    ("family", "source_address", "target_address", "network", "address_set_prefix"),
    (
        (4, "10.0.0.1", "10.0.1.1", "ip4", "as_"),
        (6, "fd00::1", "fd00:1::1", "ip6", "as6_"),
    ),
)
def test_ovn_namespace_allows_traffic_to_another_namespace(
    family: int,
    source_address: str,
    target_address: str,
    network: str,
    address_set_prefix: str,
) -> None:
    runner = FakeRunner()
    settings = {"ipv4": family == 4, "ipv6": family == 6}
    source = OvnNamespace(runner, "network-policy", "source", 0, **settings)
    target = OvnNamespace(runner, "network-policy", "target", 1, **settings)

    source.create()
    target.create()
    source.add_endpoints([{"port": "source-pod", f"ipv{family}": source_address}])
    target.add_endpoints([{"port": "target-pod", f"ipv{family}": target_address}])
    source.allow_to(target, family, priority=7)

    commands = [call[1] for call in runner.calls]
    assert (
        "ovn-nbctl",
        "--type=port-group",
        "--may-exist",
        "acl-add",
        "pg_target",
        "to-lport",
        7,
        f"{network}.src == ${address_set_prefix}source && outport == @pg_target",
        "allow-related",
    ) in commands
    assert (
        "ovn-nbctl",
        "--type=port-group",
        "--may-exist",
        "acl-add",
        "pg_source",
        "to-lport",
        7,
        f"{network}.dst == ${address_set_prefix}target && inport == @pg_source",
        "allow-related",
    ) in commands
    for port_group, port in (
        ("pg_source", "source-pod"),
        ("pg_target", "target-pod"),
    ):
        assert ("ovn-nbctl", "pg-set-ports", port_group, port) in commands

    source.cleanup()
    target.cleanup()
    source.verify_cleanup()
    target.verify_cleanup()


@pytest.mark.parametrize(
    ("family", "addresses", "network", "address_set_prefix"),
    (
        (4, ("10.0.0.1", "10.0.0.2", "10.0.0.3"), "ip4", "sub_as_"),
        (6, ("fd00::1", "fd00::2", "fd00::3"), "ip6", "sub_as6_"),
    ),
)
def test_ovn_namespace_manages_policy_groups(
    family: int,
    addresses: tuple[str, str, str],
    network: str,
    address_set_prefix: str,
) -> None:
    runner = FakeRunner()
    namespace = OvnNamespace(
        runner,
        "network-policy",
        "groups",
        0,
        ipv4=family == 4,
        ipv6=family == 6,
    )
    endpoints = [
        {"port": f"pod-{index}", f"ipv{family}": address}
        for index, address in enumerate(addresses, 1)
    ]

    namespace.create()
    namespace.add_endpoints(endpoints)
    namespace.default_deny(family)
    namespace.set_group("source", endpoints[:2])
    namespace.set_group("target", endpoints[2:])
    namespace.allow_between("source", "target", family, priority=7)

    source_port_group = "sub_pg_groups_0"
    target_port_group = "sub_pg_groups_1"
    source_address_set = f"{address_set_prefix}groups_0"
    target_address_set = f"{address_set_prefix}groups_1"
    commands = [call[1] for call in runner.calls]
    assert (
        "ovn-nbctl",
        "pg-set-ports",
        source_port_group,
        "pod-1",
        "pod-2",
    ) in commands
    assert (
        "ovn-nbctl",
        "pg-set-ports",
        target_port_group,
        "pod-3",
    ) in commands
    for match in (
        f"{network}.src == ${source_address_set} && outport == @{target_port_group}",
        f"{network}.dst == ${target_address_set} && inport == @{source_port_group}",
    ):
        assert any(
            "acl-add" in command
            and command[-2:] == (match, "allow-related")
            and 7 in command
            for command in commands
        )

    previous_calls = len(runner.calls)
    namespace.set_group("source", endpoints[1:2])
    reconfiguration = [call[1] for call in runner.calls[previous_calls:]]
    assert reconfiguration[0] == (
        "ovn-nbctl",
        "pg-set-ports",
        source_port_group,
        "pod-2",
    )
    assert reconfiguration[1][1:3] == ("clear", "Address_Set")
    assert reconfiguration[2][-1] == f'"{addresses[1]}"'
    assert not any("pg-add" in command for command in reconfiguration)

    namespace.allow_between("source", "target", family, priority=8)
    assert any(
        command[:3] == ("ovn-nbctl", "--type=port-group", "acl-del") and 7 in command
        for command in (call[1] for call in runner.calls)
    )

    previous_calls = len(runner.calls)
    namespace.cleanup()
    namespace.verify_cleanup()
    cleanup_queries = [call[1] for call in runner.calls[previous_calls:]]
    for name in (
        source_port_group,
        target_port_group,
        source_address_set,
        target_address_set,
    ):
        assert any(command[-1] == f'name="{name}"' for command in cleanup_queries)


def test_ovn_namespace_rejects_invalid_policy_groups() -> None:
    namespace = OvnNamespace(FakeRunner(), "network-policy", "groups", 0)

    with pytest.raises(ValueError, match="name cannot be empty"):
        namespace.set_group("", [])
    namespace.set_group("source", [])
    with pytest.raises(ValueError, match="does not exist: target"):
        namespace.allow_between("source", "target", 4)


def test_ovn_namespace_rejects_invalid_policy_addresses() -> None:
    namespace = OvnNamespace(
        FakeRunner(),
        "network-policy",
        "NS_policy_0",
        0,
        ipv6=False,
    )

    with pytest.raises(ValueError, match="IPv6 is disabled"):
        namespace.default_deny(6)
    with pytest.raises(ValueError, match="at least one address"):
        namespace.allow_external([])
    with pytest.raises(ValueError, match="must be IPv4"):
        namespace.allow_external(["2001:db8::1"])


def test_ovn_namespace_cleans_partially_created_address_sets() -> None:
    runner = FakeRunner()
    namespace = OvnNamespace(
        runner,
        "cluster-density",
        "NS_density_0",
        0,
    )
    runner.fail.add(
        (
            "ovn-nbctl",
            "create",
            "Address_Set",
            'name="as6_NS_density_0"',
            'external_ids:ovn-tmt-tests-owner="cluster-density"',
        )
    )

    with pytest.raises(subprocess.CalledProcessError):
        namespace.create()
    runner.fail.clear()
    namespace.cleanup()

    commands = [call[1] for call in runner.calls]
    for name in ("as_NS_density_0", "as6_NS_density_0"):
        assert (
            "ovn-nbctl",
            "--bare",
            "--columns=_uuid",
            "find",
            "Address_Set",
            f'name="{name}"',
        ) in commands


@pytest.mark.parametrize(
    "values",
    (
        {"startup": -1},
        {"startup": 3, "total": 2},
        {"total": 0},
        {"build_pods": -1},
        {"test_pods": 3},
        {"protocols": []},
        {"protocols": ["tcp", "tcp"]},
        {"protocols": ["tcp", "http"]},
        {"timeout": 0},
        {"ipv4": False, "ipv6": False},
        {"ipv4": "true"},
        {"ipv6": False, "mtu": 575},
        {"mtu": 65536},
        {"chassis": 1},
        {"workers": 0},
        {"base_pods": -1},
        {"startup": 0, "total": 65535, "build_pods": 0},
    ),
)
def test_cluster_density_validation_rejects_invalid_values(values: Any) -> None:
    config = {
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
    config.update(values)

    with pytest.raises(ValueError, match=r".+"):
        validate_cluster_density(**config)


def test_cluster_density_validation_accepts_original_defaults() -> None:
    validate_cluster_density(
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
