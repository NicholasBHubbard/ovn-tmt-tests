import subprocess
from collections.abc import Callable
from unittest.mock import Mock

import pytest
from ovn_test.command import Runner
from ovn_test.load_balancer import DEFAULT_OPTIONS, LoadBalancers, socket


def _runner(*outputs: str) -> tuple[Mock, subprocess.CompletedProcess[str]]:
    result = subprocess.CompletedProcess(["ovn-nbctl"], 0, "updated\n", "")
    runner = Mock(spec=Runner)
    runner.output.side_effect = outputs
    runner.run.return_value = result
    return runner, result


def _contains(command: tuple[object, ...], *parts: object) -> bool:
    return any(
        command[index : index + len(parts)] == parts
        for index in range(len(command) - len(parts) + 1)
    )


def test_socket_formats_and_normalizes_addresses() -> None:
    assert socket("192.0.2.1", 80, 4) == "192.0.2.1:80"
    assert socket("2001:0db8:0:0::1", 443, 6) == "[2001:db8::1]:443"


@pytest.mark.parametrize(
    ("address", "port", "family", "message"),
    (
        ("192.0.2.1", 80, 5, "family"),
        ("192.0.2.1", 80, 6, "not an IPv6"),
        ("not-an-address", 80, 4, "invalid IP"),
        ("192.0.2.1", 0, 4, "port"),
        ("192.0.2.1", 65536, 4, "port"),
        ("192.0.2.1", True, 4, "port"),
    ),
)
def test_socket_rejects_invalid_values(
    address: str, port: int, family: int, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        socket(address, port, family)


def test_replace_creates_an_owner_scoped_load_balancer() -> None:
    runner, completed = _runner("")
    load_balancers = LoadBalancers(runner, 'owner "one"')

    result = load_balancers.replace(
        'load balancer "one"',
        "tcp",
        {"192.0.2.10:80": "192.0.2.20:8080"},
        switches="switch-one",
        routers=(name for name in ("router-one", "router-one")),
        group="group-one",
    )

    assert result is completed
    runner.output.assert_called_once_with(
        "ovn-nbctl",
        "--format=csv",
        "--data=bare",
        "--no-headings",
        "--columns=_uuid,name",
        "find",
        "Load_Balancer",
        'external_ids:ovn-tmt-tests-owner="owner \\"one\\""',
    )
    command = runner.run.call_args.args
    assert command[:4] == ("ovn-nbctl", "--id=@lb", "create", "Load_Balancer")
    assert 'vips:"192.0.2.10:80"="192.0.2.20:8080"' in command
    assert {argument for argument in command if argument.startswith("options:")} == {
        f'options:{key}="{value}"' for key, value in DEFAULT_OPTIONS.items()
    }
    assert _contains(
        command,
        "add",
        "Logical_Switch",
        "switch-one",
        "load_balancer",
        "@lb",
    )
    assert _contains(
        command,
        "add",
        "Logical_Router",
        "router-one",
        "load_balancer",
        "@lb",
    )
    assert command.count("router-one") == 1
    assert _contains(
        command,
        "add",
        "Load_Balancer_Group",
        "group-one",
        "load_balancer",
        "@lb",
    )


def test_replace_updates_the_managed_row_and_reconciles_attachments() -> None:
    runner, _ = _runner(
        "load-balancer-uuid,service\n",
        "old-switch-reference\n",
        "old-router-reference\n",
        "old-group-reference\n",
    )
    load_balancers = LoadBalancers(runner, "owner")

    load_balancers.replace(
        "service",
        "udp",
        {"[2001:db8::10]:53": ["[2001:db8::20]:5353"]},
        switches="new-switch",
        routers="new-router",
        group=None,
        options={"reject": "false"},
    )

    command = runner.run.call_args.args
    assert command[:13] == (
        "ovn-nbctl",
        "clear",
        "Load_Balancer",
        "load-balancer-uuid",
        "vips",
        "options",
        "--",
        "set",
        "Load_Balancer",
        "load-balancer-uuid",
        'name="service"',
        "protocol=udp",
        'external_ids:ovn-tmt-tests-owner="owner"',
    )
    assert "create" not in command
    assert 'options:reject="false"' in command
    assert not {
        argument
        for argument in command
        if argument.startswith("options:") and argument != 'options:reject="false"'
    }
    for table, row in (
        ("Logical_Switch", "old-switch-reference"),
        ("Logical_Router", "old-router-reference"),
        ("Load_Balancer_Group", "old-group-reference"),
    ):
        assert _contains(
            command,
            "remove",
            table,
            row,
            "load_balancer",
            "load-balancer-uuid",
        )
    assert _contains(
        command,
        "add",
        "Logical_Switch",
        "new-switch",
        "load_balancer",
        "load-balancer-uuid",
    )
    assert _contains(
        command,
        "add",
        "Logical_Router",
        "new-router",
        "load_balancer",
        "load-balancer-uuid",
    )
    assert not _contains(command, "add", "Load_Balancer_Group")


def test_replace_allows_empty_options_and_backends() -> None:
    runner, _ = _runner("")

    LoadBalancers(runner, "owner").replace(
        "service", "sctp", {"192.0.2.10:80": []}, options={}
    )

    command = runner.run.call_args.args
    assert 'vips:"192.0.2.10:80"=""' in command
    assert not [argument for argument in command if argument.startswith("options:")]


def test_inventory_is_loaded_once_for_many_creations() -> None:
    runner, _ = _runner("")
    runner.run.side_effect = (
        subprocess.CompletedProcess(["ovn-nbctl"], 0, "uuid-one\n", ""),
        subprocess.CompletedProcess(["ovn-nbctl"], 0, "uuid-two\n", ""),
    )
    load_balancers = LoadBalancers(runner, "owner")

    load_balancers.replace("service-one", "tcp")
    load_balancers.replace("service-two", "tcp")

    runner.output.assert_called_once()
    assert runner.run.call_count == 2


def test_replace_rejects_invalid_configuration_before_querying_ovn() -> None:
    runner, _ = _runner()
    load_balancers = LoadBalancers(runner, "owner")
    invalid: tuple[tuple[Callable[[], object], str], ...] = (
        (lambda: LoadBalancers(runner, ""), "owner"),
        (lambda: load_balancers.replace("", "tcp"), "name"),
        (lambda: load_balancers.replace("service", "icmp"), "protocol"),
        (
            lambda: load_balancers.replace("service", "tcp", switches=[""]),
            "switch name",
        ),
        (lambda: load_balancers.replace("service", "tcp", group=""), "group"),
        (
            lambda: load_balancers.replace("service", "tcp", options={"": "true"}),
            "option name",
        ),
        (
            lambda: load_balancers.replace(
                "service",
                "tcp",
                {"192.0.2.10:80": [""]},
            ),
            "backend",
        ),
    )

    for action, message in invalid:
        with pytest.raises(ValueError, match=message):
            action()
    runner.output.assert_not_called()
    runner.run.assert_not_called()


def test_replace_rejects_ambiguous_managed_identity() -> None:
    runner, _ = _runner("uuid-one,service\nuuid-two,service\n")

    with pytest.raises(RuntimeError, match="not unique"):
        LoadBalancers(runner, "owner").replace("service", "tcp")

    runner.run.assert_not_called()


def test_replace_propagates_ovn_failure() -> None:
    runner, _ = _runner("")
    failure = subprocess.CalledProcessError(7, ["ovn-nbctl"])
    runner.run.side_effect = failure

    with pytest.raises(subprocess.CalledProcessError) as error:
        LoadBalancers(runner, "owner").replace("service", "tcp")

    assert error.value is failure


def test_delete_only_removes_the_owner_scoped_row() -> None:
    runner, _ = _runner("managed-uuid,service\n")
    load_balancers = LoadBalancers(runner, "owner")

    assert load_balancers.contains("service")
    load_balancers.delete("service")
    assert not load_balancers.contains("service")

    runner.output.assert_called_once_with(
        "ovn-nbctl",
        "--format=csv",
        "--data=bare",
        "--no-headings",
        "--columns=_uuid,name",
        "find",
        "Load_Balancer",
        'external_ids:ovn-tmt-tests-owner="owner"',
    )
    runner.run.assert_called_once_with(
        "ovn-nbctl", "destroy", "Load_Balancer", "managed-uuid"
    )


def test_delete_is_quiet_when_the_managed_row_is_absent() -> None:
    runner, _ = _runner("")

    LoadBalancers(runner, "owner").delete("service")

    runner.run.assert_not_called()
