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
