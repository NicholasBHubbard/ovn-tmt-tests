import ipaddress
import os
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, Optional, Union

from ovn_test.command import Runner
from ovn_test.config import database_remote, read_bool, read_port
from ovn_test.load_balancer import VALID_PROTOCOLS, socket
from ovn_test.network import ExternalPeers
from ovn_test.ovsdb import Ovsdb
from ovn_test.system import ovsdb_control_socket
from ovn_test.topology import Topology
from ovn_test.workload import Workload


def _run_all(*actions: Callable[[], object]) -> None:
    first_error = None
    for action in actions:
        try:
            action()
        except Exception as error:
            if first_error is None:
                first_error = error
    if first_error is not None:
        raise first_error


def _baseline_protocols(protocols: Sequence[str]) -> tuple[str, ...]:
    if isinstance(protocols, (str, bytes)):
        raise ValueError("baseline protocols must be a sequence")
    result = tuple(protocols)
    if not result or any(not isinstance(protocol, str) for protocol in result):
        raise ValueError("baseline protocols must be a non-empty sequence of strings")
    if len(result) != len(set(result)):
        raise ValueError("baseline protocols must be unique")
    if set(result) - VALID_PROTOCOLS:
        raise ValueError("baseline protocols must be tcp, udp or sctp")
    return result


def verify_scale_environment(
    runner: Runner,
    topology: Topology,
    environment: Optional[Mapping[str, str]] = None,
) -> list[str]:
    environment = os.environ if environment is None else environment
    clustered = read_bool(environment, "OTT_CLUSTERED", False)
    protocol = "ssl" if read_bool(environment, "OTT_SSL_ENABLED", False) else "tcp"
    computes = topology.role("compute")
    central = topology.role("central")
    if clustered and "central-follower" in topology.roles():
        central.extend(topology.role("central-follower"))
    central = list(dict.fromkeys(central))
    if not computes:
        raise ValueError("scale testing requires at least one compute guest")
    if not central:
        raise ValueError("scale testing requires at least one central guest")

    if clustered:
        databases = (
            (
                "ovnnb_db",
                "OVN_Northbound",
                read_port(environment, "OTT_NB_RAFT_PORT", 6643),
            ),
            (
                "ovnsb_db",
                "OVN_Southbound",
                read_port(environment, "OTT_SB_RAFT_PORT", 6644),
            ),
        )
        for guest in central:
            for daemon, database, port in databases:
                status = runner.output(
                    "ovn-appctl",
                    "-t",
                    ovsdb_control_socket(runner, daemon, guest=guest),
                    "cluster/status",
                    database,
                    guest=guest,
                )
                assert "Role:" in status
                for member in central:
                    assert (
                        database_remote(
                            protocol,
                            topology.hostname(member),
                            port,
                        )
                        in status
                    )

    sb_port = read_port(environment, "OTT_SB_PORT", 6642)
    remotes = {
        database_remote(protocol, topology.hostname(guest), sb_port)
        for guest in central
    }
    monitor_all = read_bool(environment, "OTT_MONITOR_ALL", False)
    for guest in computes:
        external_ids = Ovsdb(runner, "ovs-vsctl", guest).value(
            "Open_vSwitch", "external_ids"
        )
        if not isinstance(external_ids, dict) or not all(
            isinstance(key, str) and isinstance(value, str)
            for key, value in external_ids.items()
        ):
            raise RuntimeError("invalid Open_vSwitch external IDs")
        remote = external_ids.get("ovn-remote")
        assert isinstance(remote, str)
        assert set(remote.split(",")) == remotes
        expected_monitor_all = "true" if monitor_all else None
        assert external_ids.get("ovn-monitor-all") == expected_monitor_all
    return computes


class ScaleBaseline:
    def __init__(
        self,
        runner: Runner,
        computes: Sequence[str],
        scale_topology: dict[str, Any],
        data_dir: Union[str, os.PathLike[str]],
        *,
        pods_per_worker: int,
        protocols: Sequence[str],
        ipv4: bool,
        ipv6: bool,
        mtu: int,
        timeout: int,
        sync_timeout: int,
        name: str,
        prefix: str,
        integration_bridge: str = "br-int",
    ) -> None:
        if (
            isinstance(pods_per_worker, bool)
            or not isinstance(pods_per_worker, int)
            or pods_per_worker < 0
        ):
            raise ValueError("baseline pods per worker must be non-negative")
        if (
            isinstance(sync_timeout, bool)
            or not isinstance(sync_timeout, int)
            or sync_timeout < 1
        ):
            raise ValueError("baseline sync timeout must be positive")
        self.pods_per_worker = pods_per_worker
        self.protocols = _baseline_protocols(protocols)
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
            integration_bridge=integration_bridge,
        )

    def create(self) -> None:
        count = self.pods_per_worker * len(self.workload.workers)
        self.external.create()
        for index in range(count):
            self.workload.add_endpoint(index, "base", converge=False)
        self._add_load_balancers()
        self.workload.sync()
        for index in range(count):
            self.workload.verify_connectivity(index, (index + 1) % count)
            self.external.verify(self.workload.endpoint(index))

    def _add_load_balancers(self) -> None:
        for family, enabled in (
            (4, self.workload.ipv4_enabled),
            (6, self.workload.ipv6_enabled),
        ):
            if not enabled:
                continue
            vip_network = ipaddress.ip_network("4.0.0.0/8" if family == 4 else "4::/32")
            backend_network = ipaddress.ip_network(
                "6.0.0.0/8" if family == 4 else "6::/32"
            )
            static_backends = [
                socket(str(backend_network[index]), 8080, family)
                for index in range(1, 3)
            ]
            vips = {
                socket(str(vip_network[index]), 80, family): list(static_backends)
                for index in range(1, 66)
            }
            vips[next(iter(vips))].extend(
                socket(endpoint["ipv4" if family == 4 else "ipv6"], 8080, family)
                for endpoint in self.workload.endpoints
            )
            suffix = "" if family == 4 else "6"
            for protocol in self.protocols:
                self.workload.replace_load_balancer(
                    f"lb-cluster1{suffix}-{protocol}",
                    protocol,
                    vips,
                    switches=(worker["switch"] for worker in self.workload.workers),
                    routers=(
                        worker["gateway_router"] for worker in self.workload.workers
                    ),
                )
                for worker in self.workload.workers:
                    router = worker["gateway_router"]
                    self.workload.replace_load_balancer(
                        f"lb-{router}{suffix}-{protocol}",
                        protocol,
                        routers=[router],
                    )

    def cleanup(self) -> None:
        _run_all(self.workload.cleanup, self.external.cleanup)

    def verify_cleanup(self) -> None:
        _run_all(self.workload.verify_cleanup, self.external.verify_cleanup)
