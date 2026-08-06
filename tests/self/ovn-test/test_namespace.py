import subprocess
from collections.abc import Callable
from typing import Any, Optional
from unittest.mock import Mock

import pytest
from ovn_test.command import Runner
from ovn_test.namespace import NamespaceResources, OvnNamespace


def _runner(
    inventories: Optional[dict[str, str]] = None,
) -> tuple[Mock, Callable[[], int]]:
    runner = Mock(spec=Runner)
    created = 0

    def output(*command: object) -> str:
        nonlocal created
        if "find" in command:
            return (inventories or {}).get(str(command[command.index("find") + 1]), "")
        if "create" in command:
            created += 1
            return f"uuid-{created}"
        raise AssertionError(command)

    def run(*command: object) -> subprocess.CompletedProcess[str]:
        nonlocal created
        stdout = ""
        if "Load_Balancer" in command and "create" in command:
            created += 1
            stdout = f"uuid-{created}\n"
        return subprocess.CompletedProcess(["ovn-nbctl"], 0, stdout, "")

    runner.output.side_effect = output
    runner.run.side_effect = run
    return runner, lambda: created


def _namespace(
    runner: Mock,
    name: str = "namespace",
    resources: Optional[NamespaceResources] = None,
) -> OvnNamespace:
    namespace = OvnNamespace(
        runner,
        "owner",
        name,
        0,
        ipv6=False,
        resources=resources,
    )
    namespace.create()
    return namespace


def _contains(command: tuple[object, ...], *parts: object) -> bool:
    return any(
        command[index : index + len(parts)] == parts
        for index in range(len(command) - len(parts) + 1)
    )


@pytest.mark.parametrize(
    ("arguments", "message"),
    (
        ({"owner": ""}, "owner"),
        ({"name": "bad-name"}, "identifier"),
        ({"index": -1}, "index"),
        ({"index": True}, "index"),
        ({"ipv4": False, "ipv6": False}, "IP family"),
        ({"ipv4": "true"}, "IP family"),
    ),
)
def test_constructor_rejects_invalid_identity_and_families(
    arguments: dict[str, Any], message: str
) -> None:
    runner, _ = _runner()
    values: dict[str, Any] = {
        "runner": runner,
        "owner": "owner",
        "name": "namespace",
        "index": 0,
        "ipv4": True,
        "ipv6": False,
    }
    values.update(arguments)

    with pytest.raises(ValueError, match=message):
        OvnNamespace(**values)


def test_constructor_rejects_resources_from_another_context() -> None:
    runner, _ = _runner()
    other, _ = _runner()
    resources = NamespaceResources(runner, "owner")

    with pytest.raises(ValueError, match="same runner and owner"):
        OvnNamespace(other, "owner", "namespace", 0, resources=resources)
    with pytest.raises(ValueError, match="same runner and owner"):
        OvnNamespace(runner, "other", "namespace", 0, resources=resources)


def test_shared_resources_load_each_inventory_only_once() -> None:
    runner, _ = _runner()
    resources = NamespaceResources(runner, "owner")
    first = _namespace(runner, "first", resources)
    second = _namespace(runner, "second", resources)

    assert first.resources is second.resources
    assert first.resources.load_balancers is second.resources.load_balancers
    inventory_calls = [
        call.args for call in runner.output.call_args_list if "find" in call.args
    ]
    assert len([call for call in inventory_calls if "Port_Group" in call]) == 1
    assert len([call for call in inventory_calls if "Address_Set" in call]) == 1


def test_create_reuses_managed_rows_and_reapplies_desired_state() -> None:
    runner, created = _runner()
    namespace = _namespace(runner)
    namespace.set_endpoints([{"port": "pod", "ipv4": "192.0.2.10"}])
    namespace.default_deny(4)
    created_before = created()
    runner.run.reset_mock()

    namespace.create()

    assert created() == created_before
    commands = [call.args for call in runner.run.call_args_list]
    assert any(_contains(command, "clear", "Port_Group") for command in commands)
    assert any(_contains(command, "add", "Address_Set") for command in commands)
    assert len([command for command in commands if "acl-add" in command]) == 4


def test_create_never_deletes_a_conflicting_unmanaged_name() -> None:
    runner, _ = _runner()
    failure = subprocess.CalledProcessError(1, ["ovn-nbctl"])

    def fail_create(*command: object) -> str:
        if "find" in command:
            return ""
        raise failure

    runner.output.side_effect = fail_create

    with pytest.raises(subprocess.CalledProcessError):
        OvnNamespace(runner, "owner", "collision", 0, ipv6=False).create()
    assert not any("destroy" in call.args for call in runner.run.call_args_list)
    assert not any("destroy" in call.args for call in runner.output.call_args_list)


def test_endpoints_are_copied_replaced_removed_and_idempotent() -> None:
    runner, _ = _runner()
    namespace = _namespace(runner)
    endpoint = {"port": "pod-one", "ipv4": "192.0.2.1"}

    namespace.set_endpoints([endpoint])
    endpoint["ipv4"] = "192.0.2.99"
    assert namespace.endpoints[0]["ipv4"] == "192.0.2.1"
    runner.run.reset_mock()
    namespace.set_endpoints([{"port": "pod-one", "ipv4": "192.0.2.1"}])
    runner.run.assert_not_called()

    namespace.add_endpoints([{"port": "pod-one", "ipv4": "192.0.2.2"}])
    namespace.add_endpoints([{"port": "pod-two", "ipv4": "192.0.2.3"}])
    namespace.remove_endpoints([{"port": "pod-one", "ipv4": "192.0.2.2"}])

    assert namespace.endpoints == [{"port": "pod-two", "ipv4": "192.0.2.3"}]
    command = runner.run.call_args.args
    assert '"192.0.2.3"' in command
    assert '"192.0.2.2"' not in command


def test_failed_endpoint_update_can_be_retried() -> None:
    runner, _ = _runner()
    namespace = _namespace(runner)
    failure = subprocess.CalledProcessError(1, ["ovn-nbctl"])
    runner.run.side_effect = failure
    desired = [{"port": "pod", "ipv4": "192.0.2.1"}]

    with pytest.raises(subprocess.CalledProcessError):
        namespace.set_endpoints(desired)
    assert namespace.endpoints == []

    runner.run.side_effect = lambda *command: subprocess.CompletedProcess(
        command, 0, "", ""
    )
    namespace.set_endpoints(desired)
    assert namespace.endpoints == desired


@pytest.mark.parametrize(
    ("endpoints", "message"),
    (
        ("pod", "sequence of mappings"),
        ([{}], "port"),
        ([{"port": "pod", "ipv4": "invalid"}], "invalid"),
        (
            [
                {"port": "pod", "ipv4": "192.0.2.1"},
                {"port": "pod", "ipv4": "192.0.2.2"},
            ],
            "duplicated",
        ),
    ),
)
def test_endpoints_reject_invalid_data(endpoints: Any, message: str) -> None:
    runner, _ = _runner()
    namespace = _namespace(runner)

    with pytest.raises(ValueError, match=message):
        namespace.set_endpoints(endpoints)


def test_groups_have_stable_names_and_atomic_idempotent_updates() -> None:
    first_runner, _ = _runner()
    second_runner, _ = _runner()
    first = _namespace(first_runner)
    second = _namespace(second_runner)
    endpoint = [{"port": "pod", "ipv4": "192.0.2.1"}]

    first.set_group("source", endpoint)
    first.set_group("target", endpoint)
    second.set_group("target", endpoint)
    second.set_group("source", endpoint)

    assert first.groups["source"].port_group == second.groups["source"].port_group
    assert first.groups["target"].address_sets == second.groups["target"].address_sets
    command = first_runner.run.call_args_list[-2].args
    assert _contains(command, "pg-set-ports", first.groups["source"].port_group)
    assert _contains(command, "clear", "Address_Set")
    assert _contains(command, "add", "Address_Set")
    calls = first_runner.run.call_count
    first.set_group("target", endpoint)
    assert first_runner.run.call_count == calls


def test_policy_updates_validate_skip_and_clear() -> None:
    runner, _ = _runner()
    namespace = _namespace(runner)
    namespace.set_endpoints([{"port": "pod", "ipv4": "192.0.2.1"}])
    runner.run.reset_mock()

    namespace.default_deny(4)
    calls = runner.run.call_count
    namespace.default_deny(4)
    assert runner.run.call_count == calls
    namespace.allow_from_external("198.51.100.1")
    assert any("198.51.100.1" in str(part) for part in runner.run.call_args.args)

    with pytest.raises(ValueError, match="priority"):
        namespace.allow_within(4, -1)
    namespace.clear_policies()
    assert namespace.acls == {}
    assert _contains(runner.run.call_args.args, "clear", "Port_Group")


def test_cleanup_continues_after_failure_and_can_be_retried() -> None:
    runner, _ = _runner()
    namespace = _namespace(runner)
    runner.run.reset_mock()
    failure = subprocess.CalledProcessError(1, ["ovn-nbctl"])

    def fail_first(*command: object) -> subprocess.CompletedProcess[str]:
        if command == ("ovn-nbctl", "destroy", "Port_Group", "uuid-1"):
            raise failure
        return subprocess.CompletedProcess(["ovn-nbctl"], 0, "", "")

    runner.run.side_effect = fail_first
    with pytest.raises(subprocess.CalledProcessError):
        namespace.cleanup()
    assert not namespace.cleaned
    assert runner.run.call_count == 4
    with pytest.raises(AssertionError, match="Port_Group remains"):
        namespace.verify_cleanup()

    runner.run.side_effect = lambda *command: subprocess.CompletedProcess(
        command, 0, "", ""
    )
    namespace.cleanup()
    namespace.verify_cleanup()
    assert namespace.cleaned


def test_ovn_namespace_manages_network_policy_state(fake_runner: Any) -> None:
    runner = fake_runner
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
    assert not [
        call
        for call in runner.calls
        if "pg-set-ports" in call[1] and "pod-1" in call[1]
    ]

    namespace.default_deny(4)
    namespace.allow_within(4)
    namespace.allow_from_external(
        ["42.42.42.1", "42.42.42.2"],
        name="trusted",
    )

    commands = [call[1] for call in runner.calls]
    for port_group in namespace.port_groups:
        assert any(
            _contains(command, "pg-set-ports", port_group, "pod-1", "pod-2")
            for command in commands
        )
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

    namespace.allow_from_external(["42.42.42.3"], name="trusted")
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
    assert any(
        _contains(
            call[1],
            "pg-set-ports",
            "pg_NS_policy_0",
            "pod-1",
            "pod-2",
            "pod-3",
        )
        for call in runner.calls
    )

    namespace.cleanup()
    namespace.verify_cleanup()


def test_ovn_namespace_manages_ipv6_network_policy_state(fake_runner: Any) -> None:
    runner = fake_runner
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
    namespace.allow_from_external(
        ["2001:db8::1", "2001:db8::2"],
        family=6,
        name="trusted",
    )

    commands = [call[1] for call in runner.calls]
    assert any(
        _contains(command, "add", "Address_Set") and command[-1] == '"fd00::10"'
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
    fake_runner: Any,
    family: int,
    source_address: str,
    target_address: str,
    network: str,
    address_set_prefix: str,
) -> None:
    runner = fake_runner
    settings = {"ipv4": family == 4, "ipv6": family == 6}
    source = OvnNamespace(
        runner,
        "network-policy",
        "source",
        0,
        ipv4=settings["ipv4"],
        ipv6=settings["ipv6"],
    )
    target = OvnNamespace(
        runner,
        "network-policy",
        "target",
        1,
        ipv4=settings["ipv4"],
        ipv6=settings["ipv6"],
    )

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
        assert any(
            _contains(command, "pg-set-ports", port_group, port) for command in commands
        )

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
    fake_runner: Any,
    family: int,
    addresses: tuple[str, str, str],
    network: str,
    address_set_prefix: str,
) -> None:
    runner = fake_runner
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

    source_group = namespace.groups["source"]
    target_group = namespace.groups["target"]
    source_port_group = source_group.port_group
    target_port_group = target_group.port_group
    source_address_set = source_group.address_sets[family]
    target_address_set = target_group.address_sets[family]
    commands = [call[1] for call in runner.calls]
    assert any(
        _contains(command, "pg-set-ports", source_port_group, "pod-1", "pod-2")
        for command in commands
    )
    assert any(
        _contains(command, "pg-set-ports", target_port_group, "pod-3")
        for command in commands
    )
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
    assert len(reconfiguration) == 1
    assert _contains(reconfiguration[0], "pg-set-ports", source_port_group, "pod-2")
    assert _contains(reconfiguration[0], "clear", "Address_Set")
    assert reconfiguration[0][-1] == f'"{addresses[1]}"'
    assert "create" not in reconfiguration[0]

    namespace.allow_between("source", "target", family, priority=8)
    assert any(
        command[:3] == ("ovn-nbctl", "--type=port-group", "acl-del") and 7 in command
        for command in (call[1] for call in runner.calls)
    )

    namespace.cleanup()
    namespace.verify_cleanup()
    assert namespace.cleaned


def test_ovn_namespace_rejects_invalid_policy_groups(fake_runner: Any) -> None:
    namespace = OvnNamespace(fake_runner, "network-policy", "groups", 0)
    namespace.create()

    with pytest.raises(ValueError, match="name must be a non-empty string"):
        namespace.set_group("", [])
    namespace.set_group("source", [])
    with pytest.raises(ValueError, match="does not exist: target"):
        namespace.allow_between("source", "target", 4)


def test_ovn_namespace_rejects_invalid_policy_addresses(fake_runner: Any) -> None:
    namespace = OvnNamespace(
        fake_runner,
        "network-policy",
        "NS_policy_0",
        0,
        ipv6=False,
    )
    namespace.create()

    with pytest.raises(ValueError, match="IPv6 is disabled"):
        namespace.default_deny(6)
    with pytest.raises(ValueError, match="at least one address"):
        namespace.allow_from_external([])
    with pytest.raises(ValueError, match="must be IPv4"):
        namespace.allow_from_external(["2001:db8::1"])


def test_ovn_namespace_cleans_partially_created_address_sets(fake_runner: Any) -> None:
    runner = fake_runner
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
    assert any(
        command[:3] == ("ovn-nbctl", "destroy", "Address_Set") for command in commands
    )
