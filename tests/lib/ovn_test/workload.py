import ipaddress
import json
import math
import os
import re
import time
from collections.abc import Iterable, Mapping, Sequence
from copy import deepcopy
from pathlib import Path
from typing import Callable, Optional, TypedDict, TypeVar, Union, cast

from ovn_test.command import Runner
from ovn_test.load_balancer import DEFAULT_OPTIONS, LoadBalancers
from ovn_test.namespace import NamespaceResources

T = TypeVar("T")
Network = Union[ipaddress.IPv4Network, ipaddress.IPv6Network]
_NAME = re.compile(r"^[A-Za-z0-9_.-]+$")
_OWNER = "ovn-tmt-tests-owner"


class Worker(TypedDict, total=False):
    name: str
    chassis: str
    switch: str
    gateway_router: str
    external_switch: str
    internal: dict[str, str]
    external: dict[str, str]
    join: dict[str, str]
    external_vlan: int


class Endpoint(TypedDict, total=False):
    guest: str
    namespace: str
    interface: str
    port: str
    mac: str
    ipv4: str
    ipv6: str
    switch: str
    worker: str
    gateway4: str
    gateway6: str
    prefix4: int
    prefix6: int
    removed: bool


def _command(*parts: object, check: bool = True) -> tuple[tuple[object, ...], bool]:
    return parts, check


def _positive(name: str, value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{name} must be a positive integer")


def _text(value: object, label: str, maximum: Optional[int] = None) -> str:
    if not isinstance(value, str) or not value or _NAME.fullmatch(value) is None:
        raise ValueError(f"{label} must contain only letters, numbers, '.', '_' or '-'")
    if maximum is not None and len(value) > maximum:
        raise ValueError(f"{label} must be at most {maximum} characters")
    return value


def _network(value: object, version: int, label: str) -> Network:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be an IPv{version} network")
    try:
        network = ipaddress.ip_network(value)
    except ValueError as error:
        raise ValueError(f"{label} must be an IPv{version} network") from error
    if network.version != version:
        raise ValueError(f"{label} must be an IPv{version} network")
    return network


def _families(ipv4: bool, ipv6: bool, mtu: int) -> None:
    if not isinstance(ipv4, bool) or not isinstance(ipv6, bool):
        raise ValueError("IP family settings must be booleans")
    if not ipv4 and not ipv6:
        raise ValueError("at least one IP family must be enabled")
    if isinstance(mtu, bool) or not isinstance(mtu, int):
        raise ValueError("MTU must be an integer")
    minimum_mtu = 1280 if ipv6 else 576
    if not minimum_mtu <= mtu <= 65535:
        raise ValueError(f"MTU must be between {minimum_mtu} and 65535")


def _validate_common(
    initial: int,
    iterations: int,
    timeout: int,
    ipv4: bool,
    ipv6: bool,
    mtu: int,
    chassis: int,
) -> None:
    for name, value in (
        ("initial", initial),
        ("iterations", iterations),
        ("timeout", timeout),
        ("mtu", mtu),
        ("chassis", chassis),
    ):
        _positive(name, value)
    _families(ipv4, ipv6, mtu)
    if chassis < 2 or initial < chassis:
        raise ValueError(
            "the workload requires at least one initial endpoint per chassis"
        )


def validate_light(
    initial: int,
    iterations: int,
    timeout: int,
    ipv4: bool,
    ipv6: bool,
    mtu: int,
    chassis: int,
) -> None:
    _validate_common(
        initial,
        iterations,
        timeout,
        ipv4,
        ipv6,
        mtu,
        chassis,
    )
    if initial + iterations > 65534:
        raise ValueError("the workload exceeds its endpoint address space")


def validate_heavy(
    initial: int,
    iterations: int,
    pods_per_service: int,
    protocols: Sequence[str],
    timeout: int,
    ipv4: bool,
    ipv6: bool,
    mtu: int,
    chassis: int,
) -> None:
    _validate_common(
        initial,
        iterations,
        timeout,
        ipv4,
        ipv6,
        mtu,
        chassis,
    )
    _positive("pods_per_service", pods_per_service)
    if initial % pods_per_service:
        raise ValueError("initial pods must contain complete services")
    if not isinstance(protocols, Sequence) or isinstance(protocols, (str, bytes)):
        raise ValueError("load-balancer protocols must be a sequence")
    values = tuple(protocols)
    if not values or any(not isinstance(protocol, str) for protocol in values):
        raise ValueError("load-balancer protocols must be a sequence of strings")
    if len(values) != len(set(values)):
        raise ValueError("load-balancer protocols must be unique")
    if set(values) - {"tcp", "udp", "sctp"}:
        raise ValueError("load-balancer protocols must be tcp, udp or sctp")
    if initial + iterations * pods_per_service > 65534:
        raise ValueError("the workload exceeds its endpoint address space")


class Workload:
    def __init__(
        self,
        runner: Runner,
        computes: Sequence[str],
        name: str,
        prefix: str,
        metrics_file: Union[str, os.PathLike[str]],
        ipv4: bool = True,
        ipv6: bool = True,
        mtu: int = 1342,
        timeout: int = 60,
        sync_timeout: Optional[int] = None,
        scale_topology: Optional[Mapping[str, object]] = None,
        base_ports_per_worker: int = 0,
        integration_bridge: str = "br-int",
        ipv4_network: str = "10.240.0.0/16",
        ipv6_network: str = "fd00:240::/64",
    ) -> None:
        if isinstance(computes, (str, bytes)):
            raise ValueError("computes must be a sequence of guest names")
        guests = tuple(_text(guest, "compute guest") for guest in computes)
        if not guests:
            raise ValueError("at least one compute guest is required")
        if len(guests) != len(set(guests)):
            raise ValueError("compute guests must be unique")
        self.name = _text(name, "workload name")
        self.prefix = _text(prefix, "endpoint prefix", 8)
        self.integration_bridge = _text(integration_bridge, "integration bridge", 15)
        _families(ipv4, ipv6, mtu)
        _positive("timeout", timeout)
        if sync_timeout is None:
            sync_timeout = timeout
        _positive("sync_timeout", sync_timeout)
        self.ipv4_network = _network(ipv4_network, 4, "IPv4 endpoint network")
        self.ipv6_network = _network(ipv6_network, 6, "IPv6 endpoint network")
        self.runner = runner
        self.computes = guests
        self.ipv4_enabled = ipv4
        self.ipv6_enabled = ipv6
        self.mtu = mtu
        self.timeout = timeout
        self.sync_timeout = sync_timeout
        if (
            isinstance(base_ports_per_worker, bool)
            or not isinstance(base_ports_per_worker, int)
            or base_ports_per_worker < 0
        ):
            raise ValueError("base ports per worker must be a non-negative integer")
        self.workers = self._workers(scale_topology)
        group = scale_topology.get("load_balancer_group") if scale_topology else None
        if group is not None and (not isinstance(group, str) or not group):
            raise ValueError("load-balancer group must be a non-empty string")
        self.load_balancer_group = group
        self.load_balancer_group_uuid: Optional[str] = None
        self.base_ports_per_worker = base_ports_per_worker
        self.endpoints: list[Endpoint] = []
        self._endpoint_indexes: dict[int, Endpoint] = {}
        self.load_balancers: list[str] = []
        self._load_balancer_manager = LoadBalancers(runner, self.name)
        self._namespace_resources = NamespaceResources(runner, self.name)
        self._namespace_created = False
        self._topology_created = False
        self.cleaned = False

        suffix = self.name.replace("-", "_")
        self.port_groups = [
            f"pg_{suffix}",
            f"pg_deny_igr_{suffix}",
            f"pg_deny_egr_{suffix}",
        ]
        self.address_sets = [f"as_{suffix}", f"as6_{suffix}"]
        self.address_set_ids: list[Optional[str]] = [None, None]
        self.metrics_file = Path(metrics_file)
        self.metrics_file.parent.mkdir(parents=True, exist_ok=True)
        self.metrics_file.write_text("iteration,phase,duration_ns\n", encoding="utf-8")

    def _workers(
        self, scale_topology: Optional[Mapping[str, object]]
    ) -> tuple[Worker, ...]:
        if scale_topology is None:
            return ()
        raw_workers = scale_topology.get("workers")
        if (
            not isinstance(raw_workers, Sequence)
            or isinstance(raw_workers, (str, bytes))
            or not raw_workers
        ):
            raise ValueError("scale topology workers must be a non-empty sequence")
        workers = []
        for index, raw_worker in enumerate(raw_workers):
            if not isinstance(raw_worker, Mapping):
                raise ValueError(f"scale worker {index} must be a mapping")
            worker = cast(Worker, deepcopy(dict(raw_worker)))
            for key in ("name", "chassis", "switch", "internal"):
                if key not in worker:
                    raise ValueError(f"scale worker {index} is missing {key}")
            for key in (
                "name",
                "chassis",
                "switch",
                "gateway_router",
                "external_switch",
            ):
                value = worker.get(key)
                if value is not None:
                    _text(value, f"scale worker {index} {key}")
            for key in ("internal", "external", "join"):
                networks = worker.get(key)
                if networks is not None and (
                    not isinstance(networks, Mapping)
                    or not all(
                        isinstance(family, str) and isinstance(network, str)
                        for family, network in networks.items()
                    )
                ):
                    raise ValueError(
                        f"scale worker {index} {key} must map families to networks"
                    )
            vlan = worker.get("external_vlan")
            if vlan is not None:
                if isinstance(vlan, bool) or not isinstance(vlan, int):
                    raise ValueError(
                        f"scale worker {index} external_vlan must be an integer"
                    )
                worker["external_vlan"] = vlan
            if worker["chassis"] not in self.computes:
                raise ValueError(
                    f"scale worker {worker['name']} uses unknown compute "
                    f"{worker['chassis']}"
                )
            internal = worker["internal"]
            for version, enabled in (
                (4, self.ipv4_enabled),
                (6, self.ipv6_enabled),
            ):
                if enabled:
                    _network(
                        internal.get(f"ipv{version}"),
                        version,
                        f"scale worker {worker['name']} internal IPv{version}",
                    )
            workers.append(worker)
        names = [worker["name"] for worker in workers]
        if len(names) != len(set(names)):
            raise ValueError("scale worker names must be unique")
        return tuple(workers)

    def _ensure_active(self) -> None:
        if self.cleaned:
            raise RuntimeError("a cleaned workload cannot be modified")

    def endpoint(self, index: int) -> Endpoint:
        if (
            isinstance(index, bool)
            or not isinstance(index, int)
            or not 0 <= index < 65534
        ):
            raise ValueError("endpoint index must be between 0 and 65533")
        value = index + 1
        for enabled, network in (
            (self.ipv4_enabled, self.ipv4_network),
            (self.ipv6_enabled, self.ipv6_network),
        ):
            if enabled and value >= network.num_addresses - (network.version == 4):
                raise ValueError(f"{network} endpoint address space is exhausted")
        endpoint: Endpoint = {
            "guest": self.computes[index % len(self.computes)],
            "namespace": f"{self.prefix}{index:05d}",
            "interface": f"{self.prefix}{index:05d}-p",
            "port": f"{self.name}-{index:05d}",
            "mac": (
                f"02:00:{value >> 24 & 255:02x}:{value >> 16 & 255:02x}:"
                f"{value >> 8 & 255:02x}:{value & 255:02x}"
            ),
        }
        if self.ipv4_enabled:
            endpoint["ipv4"] = str(self.ipv4_network[value])
        if self.ipv6_enabled:
            endpoint["ipv6"] = str(self.ipv6_network[value])
        if not self.workers:
            return endpoint

        worker = self.workers[index % len(self.workers)]
        value += self.base_ports_per_worker * len(self.workers)
        endpoint["mac"] = (
            f"02:00:{value >> 24 & 255:02x}:{value >> 16 & 255:02x}:"
            f"{value >> 8 & 255:02x}:{value & 255:02x}"
        )
        local_index = self.base_ports_per_worker + index // len(self.workers) + 1
        endpoint.update(
            {
                "guest": worker["chassis"],
                "switch": worker["switch"],
                "worker": worker["name"],
            }
        )
        for version, enabled in (
            (4, self.ipv4_enabled),
            (6, self.ipv6_enabled),
        ):
            if not enabled:
                continue
            network = ipaddress.ip_network(worker["internal"][f"ipv{version}"])
            if local_index >= network.num_addresses - 2:
                raise ValueError(f"worker {worker['name']} address space is exhausted")
            if version == 4:
                endpoint["ipv4"] = str(network[local_index])
                endpoint["gateway4"] = str(network[-2])
                endpoint["prefix4"] = network.prefixlen
            else:
                endpoint["ipv6"] = str(network[local_index])
                endpoint["gateway6"] = str(network[-2])
                endpoint["prefix6"] = network.prefixlen
        return endpoint

    def record_metric(self, iteration: object, phase: str, start: int) -> None:
        duration = time.monotonic_ns() - start
        with self.metrics_file.open("a", encoding="utf-8") as output:
            output.write(f"{iteration},{phase},{duration}\n")
        print(f"metric iteration={iteration} phase={phase} duration_ns={duration}")

    def measure(self, iteration: object, phase: str, action: Callable[[], T]) -> T:
        start = time.monotonic_ns()
        result = action()
        self.record_metric(iteration, phase, start)
        return result

    def _find_uuids(
        self, table: str, name: str, owned: bool = False
    ) -> tuple[str, ...]:
        conditions = [f"name={json.dumps(name)}"]
        if owned:
            conditions.append(f"external_ids:{_OWNER}={json.dumps(self.name)}")
        return tuple(
            self.runner.output(
                "ovn-nbctl",
                "--bare",
                "--columns=_uuid",
                "find",
                table,
                *conditions,
            ).split()
        )

    def _owned_uuid(self, table: str, name: str) -> Optional[str]:
        named = set(self._find_uuids(table, name))
        owned = set(self._find_uuids(table, name, owned=True))
        if named - owned:
            raise RuntimeError(f"{table} {name!r} is owned by another topology")
        if len(owned) > 1:
            raise RuntimeError(f"{table} {name!r} is not unique")
        return next(iter(owned), None)

    def _delete_owned(self, table: str, name: str) -> None:
        uuid = self._owned_uuid(table, name)
        if uuid is None:
            return
        command = {
            "Logical_Switch": "ls-del",
            "Logical_Switch_Port": "lsp-del",
        }.get(table)
        if command is None:
            self.runner.run("ovn-nbctl", "destroy", table, uuid)
        else:
            self.runner.run("ovn-nbctl", command, uuid)

    def create_namespace(self) -> None:
        self._ensure_active()
        if self._namespace_created:
            raise RuntimeError("workload namespace already exists")
        if self.endpoints:
            raise RuntimeError("workload namespace must be created before endpoints")
        self.load_balancer_group_id()
        for port_group in self.port_groups:
            self._owned_uuid("Port_Group", port_group)
            uuid = self._namespace_resources.ensure("Port_Group", port_group)
            self.runner.run("ovn-nbctl", "clear", "Port_Group", uuid, "ports", "acls")
        for family, enabled in enumerate((self.ipv4_enabled, self.ipv6_enabled)):
            if not enabled:
                continue
            name = self.address_sets[family]
            self._owned_uuid("Address_Set", name)
            uuid = self._namespace_resources.ensure("Address_Set", name)
            self.runner.run("ovn-nbctl", "clear", "Address_Set", uuid, "addresses")
            self.address_set_ids[family] = uuid
        self._namespace_created = True

    def create_topology(self) -> None:
        self._ensure_active()
        if self.workers:
            raise RuntimeError("prepared scale topology is owned by provisioning")
        if self._topology_created or self._namespace_created:
            raise RuntimeError("workload topology already exists")
        self._delete_owned("Logical_Switch", self.name)
        self.runner.run(
            "ovn-nbctl",
            "ls-add",
            self.name,
            "--",
            "set",
            "Logical_Switch",
            self.name,
            f"external_ids:{_OWNER}={json.dumps(self.name)}",
        )
        self.create_namespace()
        self._topology_created = True

    def add_endpoint(
        self,
        index: int,
        phase: str,
        passive: bool = False,
        converge: bool = True,
    ) -> Endpoint:
        self._ensure_active()
        existing = self._endpoint_indexes.get(index)
        if existing is not None:
            if not existing.get("removed"):
                raise RuntimeError(f"endpoint {index} already exists")
            self.endpoints.remove(existing)
        endpoint = self.endpoint(index)
        self.endpoints.append(endpoint)
        self._endpoint_indexes[index] = endpoint
        addresses = [endpoint["mac"]]
        if self.ipv4_enabled:
            addresses.append(endpoint["ipv4"])
        if self.ipv6_enabled:
            addresses.append(endpoint["ipv6"])

        start = time.monotonic_ns()
        self._delete_owned("Logical_Switch_Port", endpoint["port"])
        self.runner.run(
            "ovn-nbctl",
            "lsp-add",
            endpoint.get("switch", self.name),
            endpoint["port"],
            "--",
            "lsp-set-addresses",
            endpoint["port"],
            " ".join(addresses),
            "--",
            "lsp-set-port-security",
            endpoint["port"],
            " ".join(addresses),
            "--",
            "set",
            "Logical_Switch_Port",
            endpoint["port"],
            f"external_ids:{_OWNER}={json.dumps(self.name)}",
        )
        for family, enabled in enumerate((self.ipv4_enabled, self.ipv6_enabled)):
            if enabled and self.address_set_ids[family] is not None:
                address = endpoint["ipv4" if family == 0 else "ipv6"]
                self.runner.run(
                    "ovn-nbctl",
                    "add",
                    "Address_Set",
                    self.address_set_ids[family],
                    "addresses",
                    f'"{address}"',
                )
        self.record_metric(index, f"{phase}_nb", start)

        start = time.monotonic_ns()
        namespace = endpoint["namespace"]
        interface = endpoint["interface"]
        peer = f"{namespace}-n"
        ip = ("ip", "-n", namespace)
        commands = [
            _command(
                "ovs-vsctl",
                "--if-exists",
                "del-port",
                self.integration_bridge,
                interface,
            ),
            _command("ip", "link", "delete", interface, check=False),
            _command("ip", "netns", "delete", namespace, check=False),
        ]
        if not passive:
            commands.extend(
                [
                    _command("ip", "netns", "add", namespace),
                    _command(
                        "ip",
                        "link",
                        "add",
                        interface,
                        "type",
                        "veth",
                        "peer",
                        "name",
                        peer,
                    ),
                    _command("ip", "link", "set", peer, "netns", namespace),
                    _command(*ip, "link", "set", peer, "name", "eth0"),
                    _command("ip", "link", "set", interface, "mtu", self.mtu, "up"),
                    _command(*ip, "link", "set", "lo", "up"),
                    _command(
                        *ip,
                        "link",
                        "set",
                        "eth0",
                        "address",
                        endpoint["mac"],
                        "mtu",
                        self.mtu,
                        "up",
                    ),
                ]
            )
            if self.ipv4_enabled:
                commands.append(
                    _command(
                        *ip,
                        "address",
                        "replace",
                        f"{endpoint['ipv4']}/"
                        f"{endpoint.get('prefix4', self.ipv4_network.prefixlen)}",
                        "dev",
                        "eth0",
                    )
                )
                if "gateway4" in endpoint:
                    commands.append(
                        _command(
                            *ip,
                            "route",
                            "replace",
                            "default",
                            "via",
                            endpoint["gateway4"],
                        )
                    )
            if self.ipv6_enabled:
                commands.append(
                    _command(
                        *ip,
                        "-6",
                        "address",
                        "replace",
                        f"{endpoint['ipv6']}/"
                        f"{endpoint.get('prefix6', self.ipv6_network.prefixlen)}",
                        "dev",
                        "eth0",
                        "nodad",
                    )
                )
                if "gateway6" in endpoint:
                    commands.append(
                        _command(
                            *ip,
                            "-6",
                            "route",
                            "replace",
                            "default",
                            "via",
                            endpoint["gateway6"],
                        )
                    )
        commands.append(
            _command(
                "ovs-vsctl",
                "--may-exist",
                "add-port",
                self.integration_bridge,
                interface,
                "--",
                "set",
                "Interface",
                interface,
                *(["type=internal"] if passive else []),
                f"external_ids:iface-id={endpoint['port']}",
            )
        )
        self.runner.run_many(commands, guest=endpoint["guest"])
        self.record_metric(index, f"{phase}_attach", start)

        if converge:
            start = time.monotonic_ns()
            self.sync()
            self.wait_for_binding(endpoint["port"])
            self.record_metric(index, f"{phase}_convergence", start)
        return endpoint

    def wait_for_binding(self, port: str) -> None:
        self.runner.wait(
            "ovn-sbctl",
            "--bare",
            "--columns=chassis",
            "find",
            "Port_Binding",
            f"logical_port={port}",
            attempts=max(1, math.ceil(self.timeout / 0.2)),
            interval=0.2,
            until=lambda result: bool(result.stdout.strip("[] \n\t")),
        )

    def sync(self) -> None:
        self.runner.run(
            "ovn-nbctl",
            "--wait=hv",
            f"--timeout={self.sync_timeout}",
            "sync",
        )

    def replace_load_balancer(
        self,
        name: str,
        protocol: str,
        vips: Optional[Mapping[str, Union[str, Sequence[str]]]] = None,
        switches: Union[str, Iterable[str]] = (),
        routers: Union[str, Iterable[str]] = (),
        group: Optional[str] = None,
        options: Mapping[str, str] = DEFAULT_OPTIONS,
    ) -> None:
        self._ensure_active()
        if name not in self.load_balancers:
            self.load_balancers.append(name)
        self._load_balancer_manager.replace(
            name,
            protocol,
            vips,
            switches,
            routers,
            group,
            options,
        )

    def load_balancer_group_id(self) -> Optional[str]:
        if self.load_balancer_group and self.load_balancer_group_uuid is None:
            self.load_balancer_group_uuid = self._named_uuid(
                "Load_Balancer_Group", self.load_balancer_group
            )
        return self.load_balancer_group_uuid

    def verify_connectivity(
        self, index: int, target_index: Optional[int] = None
    ) -> None:
        source = self.endpoint(index)
        if target_index is None:
            target_index = (index % len(self.computes) + 1) % len(self.computes)
        target = self.endpoint(target_index)
        start = time.monotonic_ns()
        for family, enabled in (
            (4, self.ipv4_enabled),
            (6, self.ipv6_enabled),
        ):
            if not enabled:
                continue
            destination = target["ipv4" if family == 4 else "ipv6"]
            self.runner.wait(
                "ip",
                "netns",
                "exec",
                source["namespace"],
                "ping",
                "-q",
                "-c",
                "1",
                "-W",
                "1",
                destination,
                guest=source["guest"],
                attempts=self.timeout,
                interval=1,
            )
        self.record_metric(index, "connectivity", start)

    def _remove_endpoint(self, endpoint: Endpoint) -> None:
        self._delete_owned("Logical_Switch_Port", endpoint["port"])
        self.runner.run_many(
            [
                _command(
                    "ovs-vsctl",
                    "--if-exists",
                    "del-port",
                    self.integration_bridge,
                    endpoint["interface"],
                ),
                _command("ip", "link", "delete", endpoint["interface"], check=False),
                _command("ip", "netns", "delete", endpoint["namespace"], check=False),
            ],
            guest=endpoint["guest"],
        )
        endpoint["removed"] = True

    def remove_endpoint(self, endpoint: Endpoint) -> None:
        self._ensure_active()
        if not any(candidate is endpoint for candidate in self.endpoints):
            raise ValueError("endpoint is not owned by this workload")
        if endpoint.get("removed"):
            raise RuntimeError("endpoint is already removed")
        self._remove_endpoint(endpoint)

    def _named_uuid(self, table: str, name: str) -> str:
        output = self.runner.output(
            "ovn-nbctl",
            "--bare",
            "--columns=_uuid",
            "find",
            table,
            f"name={json.dumps(name)}",
        )
        matches = output.split()
        if len(matches) != 1:
            raise RuntimeError(f"expected one {table} named {name!r}")
        return matches[0]

    def cleanup(self) -> None:
        if self.cleaned:
            return
        start = time.monotonic_ns()
        first_error: Optional[Exception] = None

        def attempt(action: Callable[[], object]) -> None:
            nonlocal first_error
            try:
                action()
            except Exception as error:
                if first_error is None:
                    first_error = error

        for endpoint in self.endpoints:
            if endpoint.get("removed"):
                continue
            attempt(lambda endpoint=endpoint: self._remove_endpoint(endpoint))
        for load_balancer in self.load_balancers:
            attempt(lambda name=load_balancer: self._load_balancer_manager.delete(name))
        if not self.workers:
            attempt(lambda: self._delete_owned("Logical_Switch", self.name))
        for port_group in self.port_groups:
            attempt(
                lambda name=port_group: self._namespace_resources.delete(
                    "Port_Group", name
                )
            )
        for address_set in self.address_sets:
            attempt(
                lambda name=address_set: self._namespace_resources.delete(
                    "Address_Set", name
                )
            )
        attempt(
            lambda: self.runner.run(
                "ovn-nbctl",
                "--wait=hv",
                f"--timeout={self.sync_timeout}",
                "sync",
            )
        )
        self.cleaned = first_error is None
        self.record_metric("cleanup", "cleanup", start)
        if first_error is not None:
            raise first_error

    def verify_cleanup(self) -> None:
        objects = [
            *(("Load_Balancer", name) for name in self.load_balancers),
            *(("Logical_Switch_Port", endpoint["port"]) for endpoint in self.endpoints),
            *(("Port_Group", name) for name in self.port_groups),
            *(("Address_Set", name) for name in self.address_sets),
        ]
        if not self.workers:
            objects.insert(0, ("Logical_Switch", self.name))
        else:
            for switch in {worker["switch"] for worker in self.workers}:
                self._named_uuid("Logical_Switch", switch)
        for table, name in objects:
            output = self.runner.output(
                "ovn-nbctl",
                "--bare",
                "--columns=name",
                "find",
                table,
                f"name={json.dumps(name)}",
                f"external_ids:{_OWNER}={json.dumps(self.name)}",
            )
            if output:
                raise AssertionError(f"{table} remains after cleanup: {name}")

        guest_state = {}
        for guest in dict.fromkeys(endpoint["guest"] for endpoint in self.endpoints):
            namespaces = self.runner.output("ip", "netns", "list", guest=guest)
            ports = self.runner.output(
                "ovs-vsctl",
                "list-ports",
                self.integration_bridge,
                guest=guest,
            )
            guest_state[guest] = (
                {
                    line.split(maxsplit=1)[0]
                    for line in namespaces.splitlines()
                    if line.strip()
                },
                set(ports.splitlines()),
            )

        for endpoint in self.endpoints:
            namespaces, ports = guest_state[endpoint["guest"]]
            if endpoint["namespace"] in namespaces:
                raise AssertionError(
                    f"network namespace remains after cleanup: {endpoint['namespace']}"
                )
            if endpoint["interface"] in ports:
                raise AssertionError(
                    f"OVS port remains after cleanup: {endpoint['interface']}"
                )
