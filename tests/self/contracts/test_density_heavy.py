import ipaddress
import runpy
from pathlib import Path

import pytest
from ovn_test.workload import Workload
from self._support import FakeRunner, contains


def test_density_heavy_creates_configured_service_load_balancers(
    tree: Path, tmp_path: Path
) -> None:
    module = runpy.run_path(str(tree / "tests/ovn-scale-testing/density-heavy/test.py"))
    runner = FakeRunner()
    workload = Workload(
        runner,
        ["compute-1", "compute-2"],
        "density-heavy",
        "dh",
        tmp_path / "metrics.csv",
    )

    module["add_service"](
        workload,
        3,
        7,
        ["tcp", "udp", "sctp"],
        {
            4: ipaddress.ip_network("192.0.2.0/24"),
            6: ipaddress.ip_network("2001:db8::/64"),
        },
        81,
        8081,
    )

    commands = [call[1] for call in runner.calls]
    load_balancers = [
        command for command in commands if contains(command, "create", "Load_Balancer")
    ]
    assert len(load_balancers) == 6
    assert any(
        'name="density-heavy-00003-tcp-v4"' in command
        and 'vips:"192.0.2.4:81"="10.240.0.8:8081"' in command
        for command in load_balancers
    )
    assert any(
        'name="density-heavy-00003-tcp-v6"' in command
        and 'vips:"[2001:db8::4]:81"="[fd00:240::8]:8081"' in command
        for command in load_balancers
    )
    with pytest.raises(ValueError, match="address space"):
        module["add_service"](
            workload,
            2,
            0,
            ["tcp"],
            {
                4: ipaddress.ip_network("192.0.2.0/30"),
                6: ipaddress.ip_network("2001:db8::/126"),
            },
            80,
            8080,
        )
