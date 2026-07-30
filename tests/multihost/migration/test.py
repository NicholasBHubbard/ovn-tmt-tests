from typing import Any, Callable

import pytest
from ovn_test.command import Runner
from ovn_test.network import Network

pytestmark = pytest.mark.usefixtures("setup_scenario")


def test_live_migration(runner: Runner, network: Callable[[str], Network]) -> None:
    source = network("compute-1")
    destination = network("compute-3")

    def request_chassis(value: Any, check: bool = True) -> None:
        runner.run(
            "ovn-nbctl",
            "--wait=hv",
            "set",
            "Logical_Switch_Port",
            "mig-port",
            f"options:requested-chassis={value}",
            check=check,
        )

    try:
        request_chassis("compute-1", check=False)
        source.wait_for_ping("mig-src", "10.30.0.2")
        assert not destination.ping("mig-dst", "10.30.0.2", count=2)

        request_chassis("compute-1,compute-3")
        source.wait_for_ping("mig-src", "10.30.0.2")
        destination.wait_for_ping("mig-dst", "10.30.0.2")

        request_chassis("compute-3")
        assert not source.ping("mig-src", "10.30.0.2", count=2)
        destination.wait_for_ping("mig-dst", "10.30.0.2")

        runner.run(
            "ovs-vsctl",
            "remove",
            "Interface",
            "mig-src-p",
            "external_ids",
            "iface-id",
            guest="compute-1",
        )
        runner.run(
            "ovn-appctl",
            "-t",
            "ovn-controller",
            "recompute",
            guest="compute-1",
        )
        runner.run("ovn-nbctl", "--wait=sb", "sync")
        destination.wait_for_ping("mig-dst", "10.30.0.2")
    finally:
        runner.run(
            "ovs-vsctl",
            "set",
            "Interface",
            "mig-src-p",
            "external_ids:iface-id=mig-port",
            guest="compute-1",
            check=False,
        )
        request_chassis("compute-1")
