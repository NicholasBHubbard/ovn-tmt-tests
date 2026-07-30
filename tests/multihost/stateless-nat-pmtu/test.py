from typing import Callable

import pytest
from ovn_test.command import Runner
from ovn_test.network import Network

pytestmark = pytest.mark.usefixtures("setup_scenario")


def test_stateless_nat_preserves_pmtu(
    runner: Runner, network: Callable[[str], Network]
) -> None:
    network("compute-1").wait_for_ping("snat-internal", "172.19.1.2")
    runner.namespace(
        "snat-router",
        "ip",
        "link",
        "set",
        "dev",
        "snat-down",
        "mtu",
        "1100",
        guest="gateway-1",
    )
    result = runner.namespace(
        "snat-internal",
        "ping",
        "-c",
        "20",
        "-i",
        "0.2",
        "-s",
        "1300",
        "-M",
        "do",
        "172.19.1.2",
        guest="compute-1",
        check=False,
    )

    assert "mtu = 1100" in result.stdout + result.stderr
