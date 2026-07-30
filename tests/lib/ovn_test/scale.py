import os
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence, Union

from ovn_test.config import read_bool
from ovn_test.network import ExternalPeers
from ovn_test.system import ovsdb_control_socket
from ovn_test.topology import Topology
from ovn_test.workload import Workload


def verify_scale_environment(
    runner: Any,
    topology: Topology,
    environment: Optional[Mapping[str, str]] = None,
) -> list[str]:
    environment = os.environ if environment is None else environment
    computes = topology.role("compute")
    central = topology.role("central")
    if read_bool(environment, "OTT_CLUSTERED", False):
        central += topology.data["roles"].get("central-follower", [])
        addresses = [topology.hostname(guest) for guest in central]
        for guest in central:
            for daemon, database, port in (
                ("ovnnb_db", "OVN_Northbound", 6643),
                ("ovnsb_db", "OVN_Southbound", 6644),
            ):
                status = runner.output(
                    "ovn-appctl",
                    "-t",
                    ovsdb_control_socket(runner, daemon, guest=guest),
                    "cluster/status",
                    database,
                    guest=guest,
                )
                assert "Role:" in status
                for address in addresses:
                    assert f"tcp:{address}:{port}" in status

    protocol = "ssl" if read_bool(environment, "OTT_SSL_ENABLED", False) else "tcp"
    remotes = {
        f"{protocol}:{topology.hostname(guest)}:{environment['OTT_SB_PORT']}"
        for guest in central
    }
    monitor_all = read_bool(environment, "OTT_MONITOR_ALL", False)
    for guest in computes:
        remote = runner.output(
            "ovs-vsctl",
            "get",
            "open",
            ".",
            "external-ids:ovn-remote",
            guest=guest,
        )
        assert set(remote.strip('"').split(",")) == remotes
        result = runner.run(
            "ovs-vsctl",
            "get",
            "open",
            ".",
            "external-ids:ovn-monitor-all",
            guest=guest,
            check=False,
        )
        configured = (
            result.returncode == 0 and result.stdout.strip().strip('"') == "true"
        )
        assert configured is monitor_all
    return computes


class ScaleBaseline:
    def __init__(
        self,
        runner: Any,
        computes: Sequence[str],
        scale_topology: dict[str, Any],
        data_dir: Union[str, os.PathLike[str]],
        pods_per_worker: int,
        protocols: Sequence[str],
        ipv4: bool,
        ipv6: bool,
        mtu: int,
        timeout: int,
        sync_timeout: int,
        name: str,
        prefix: str,
    ) -> None:
        self.pods_per_worker = pods_per_worker
        self.protocols = protocols
        self.external = ExternalPeers(
            runner,
            scale_topology,
            ipv4=ipv4,
            ipv6=ipv6,
            mtu=mtu,
            timeout=timeout,
        )
        self.workload = Workload(
            runner,
            computes,
            name,
            prefix,
            Path(data_dir) / "base-metrics.csv",
            ipv4=ipv4,
            ipv6=ipv6,
            mtu=mtu,
            timeout=timeout,
            sync_timeout=sync_timeout,
            scale_topology=scale_topology,
        )

    def create(self) -> None:
        count = self.pods_per_worker * len(self.workload.workers)
        self.external.create()
        for index in range(count):
            self.workload.add_endpoint(index, "base", converge=False)
        self.workload.add_background_load_balancers(self.protocols)
        self.workload.sync()
        for index in range(count):
            self.workload.verify_connectivity(index, (index + 1) % count)
            self.external.verify(self.workload.endpoint(index))

    def cleanup(self) -> None:
        try:
            self.workload.cleanup()
        finally:
            self.external.cleanup()

    def verify_cleanup(self) -> None:
        self.workload.verify_cleanup()
        self.external.verify_cleanup()
