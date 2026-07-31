import os
from pathlib import Path

from ovn_test.command import Runner


def supports_dpdk(version: str) -> bool:
    return any(line.startswith("DPDK ") for line in version.splitlines())


def test_ovs_vswitchd_has_dpdk_support(runner: Runner, source: Path) -> None:
    ovs_vswitchd = source / "ovs/vswitchd/ovs-vswitchd"

    assert os.access(ovs_vswitchd, os.X_OK), f"{ovs_vswitchd} is not executable"
    assert supports_dpdk(runner.output(ovs_vswitchd, "--version"))
