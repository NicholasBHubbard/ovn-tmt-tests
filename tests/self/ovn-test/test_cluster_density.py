import subprocess
from typing import Any
from unittest.mock import Mock

import pytest
from ovn_test.cluster_density import add_namespace_services
from ovn_test.command import Runner
from ovn_test.namespace import OvnNamespace


def _namespace() -> tuple[Mock, OvnNamespace]:
    runner = Mock(spec=Runner)
    next_uuid = 0

    def output(*command: object) -> str:
        nonlocal next_uuid
        if "find" in command:
            return ""
        next_uuid += 1
        return f"uuid-{next_uuid}"

    def run(*command: object) -> subprocess.CompletedProcess[str]:
        nonlocal next_uuid
        stdout = ""
        if "Load_Balancer" in command and "create" in command:
            next_uuid += 1
            stdout = f"uuid-{next_uuid}\n"
        return subprocess.CompletedProcess(["ovn-nbctl"], 0, stdout, "")

    runner.output.side_effect = output
    runner.run.side_effect = run
    namespace = OvnNamespace(runner, "owner", "services", 0, ipv6=False)
    namespace.create()
    runner.run.reset_mock()
    return runner, namespace


def test_services_honor_configured_network_and_ports() -> None:
    runner, namespace = _namespace()
    endpoints = [
        {"port": f"pod-{index}", "ipv4": f"10.0.0.{index}"} for index in range(1, 5)
    ]

    add_namespace_services(
        namespace,
        endpoints,
        ["tcp"],
        "group",
        ipv4_vip_network="192.0.2.0/24",
        vip_port=443,
        backend_port=8443,
    )

    command = runner.run.call_args.args
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
def test_services_reject_invalid_configuration_before_creating_a_load_balancer(
    options: dict[str, Any], message: str
) -> None:
    runner, namespace = _namespace()
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
        add_namespace_services(**values)
    assert not any("Load_Balancer" in call.args for call in runner.run.call_args_list)
