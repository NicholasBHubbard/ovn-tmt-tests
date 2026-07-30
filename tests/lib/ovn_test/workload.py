import ipaddress
import json
import math
import os
import time
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Optional, Sequence, TypeVar, Union

from ovn_test.load_balancer import replace, socket

T = TypeVar("T")


def _command(*parts: object, check: bool = True) -> tuple[tuple[object, ...], bool]:
    return parts, check


def _positive(name: str, value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{name} must be a positive integer")


def _validate_common(
    initial: int,
    iterations: int,
    timeout: int,
    ipv4: bool,
    ipv6: bool,
    mtu: int,
    chassis: int,
    total: int,
) -> None:
    for name, value in (
        ("initial", initial),
        ("iterations", iterations),
        ("timeout", timeout),
        ("mtu", mtu),
        ("chassis", chassis),
    ):
        _positive(name, value)
    if not isinstance(ipv4, bool) or not isinstance(ipv6, bool):
        raise ValueError("IP family settings must be booleans")
    if not ipv4 and not ipv6:
        raise ValueError("at least one IP family must be enabled")
    if chassis < 2 or initial < chassis:
        raise ValueError(
            "the workload requires at least one initial endpoint per chassis"
        )
    minimum_mtu = 1280 if ipv6 else 576
    if not minimum_mtu <= mtu <= 65535:
        raise ValueError(f"MTU must be between {minimum_mtu} and 65535")
    if total > 65534:
        raise ValueError("the workload exceeds its endpoint address space")


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
        initial + iterations,
    )


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
    _positive("pods_per_service", pods_per_service)
    if initial % pods_per_service:
        raise ValueError("initial pods must contain complete services")
    if len(protocols) != len(set(protocols)) or not protocols:
        raise ValueError("load-balancer protocols must be unique")
    if set(protocols) - {"tcp", "udp", "sctp"}:
        raise ValueError("load-balancer protocols must be tcp, udp or sctp")
    _validate_common(
        initial,
        iterations,
        timeout,
        ipv4,
        ipv6,
        mtu,
        chassis,
        initial + iterations * pods_per_service,
    )


def load_scale_topology(
    path: Union[str, os.PathLike[str]], computes: Sequence[str]
) -> dict[str, Any]:
    topology = json.loads(Path(path).read_text())
    workers = topology.get("workers", [])
    if not workers:
        raise ValueError("scale topology does not contain workers")
    required = {"name", "chassis", "switch", "internal"}
    if any(required - worker.keys() for worker in workers):
        raise ValueError("scale topology worker is incomplete")
    unknown = {worker["chassis"] for worker in workers} - set(computes)
    if unknown:
        raise ValueError(f"scale topology uses unknown chassis: {sorted(unknown)}")
    if not topology.get("load_balancer_group"):
        raise ValueError("scale topology does not contain a load balancer group")
    return topology


class Workload:
    def __init__(
        self,
        runner: Any,
        computes: Sequence[str],
        name: str,
        prefix: str,
        metrics_file: Union[str, os.PathLike[str]],
        ipv4: bool = True,
        ipv6: bool = True,
        mtu: int = 1342,
        timeout: int = 60,
        sync_timeout: Optional[int] = None,
        scale_topology: Optional[dict[str, Any]] = None,
        base_ports_per_worker: int = 0,
    ) -> None:
        self.runner = runner
        self.computes = computes
        self.name = name
        self.prefix = prefix
        self.ipv4_enabled = ipv4
        self.ipv6_enabled = ipv6
        self.mtu = mtu
        self.timeout = timeout
        self.sync_timeout = timeout if sync_timeout is None else sync_timeout
        if (
            isinstance(base_ports_per_worker, bool)
            or not isinstance(base_ports_per_worker, int)
            or base_ports_per_worker < 0
        ):
            raise ValueError("base ports per worker must be a non-negative integer")
        self.workers = scale_topology["workers"] if scale_topology else []
        self.load_balancer_group = (
            scale_topology["load_balancer_group"] if scale_topology else None
        )
        self.load_balancer_group_uuid = None
        self.base_ports_per_worker = base_ports_per_worker
        self.endpoints = []
        self.load_balancers = []
        self.cleaned = False

        suffix = name.replace("-", "_")
        self.port_groups = [
            f"pg_{suffix}",
            f"pg_deny_igr_{suffix}",
            f"pg_deny_egr_{suffix}",
        ]
        self.address_sets = [f"as_{suffix}", f"as6_{suffix}"]
        self.address_set_ids = [None, None]
        self.metrics_file = Path(metrics_file)
        self.metrics_file.parent.mkdir(parents=True, exist_ok=True)
        self.metrics_file.write_text("iteration,phase,duration_ns\n")

    def endpoint(self, index: int) -> dict[str, Any]:
        value = index + 1
        endpoint: dict[str, Any] = {
            "guest": self.computes[index % len(self.computes)],
            "namespace": f"{self.prefix}{index:05d}",
            "interface": f"{self.prefix}{index:05d}-p",
            "port": f"{self.name}-{index:05d}",
            "mac": "02:00:{:02x}:{:02x}:{:02x}:{:02x}".format(
                value >> 24 & 255,
                value >> 16 & 255,
                value >> 8 & 255,
                value & 255,
            ),
            "ipv4": f"10.240.{value >> 8 & 255}.{value & 255}",
            "ipv6": f"fd00:240::{value:x}",
        }
        if not self.workers:
            return endpoint

        worker = self.workers[index % len(self.workers)]
        value += self.base_ports_per_worker * len(self.workers)
        endpoint["mac"] = "02:00:{:02x}:{:02x}:{:02x}:{:02x}".format(
            value >> 24 & 255,
            value >> 16 & 255,
            value >> 8 & 255,
            value & 255,
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
            endpoint[f"ipv{version}"] = str(network[local_index])
            endpoint[f"gateway{version}"] = str(network[-2])
            endpoint[f"prefix{version}"] = network.prefixlen
        return endpoint

    def service_name(self, service: int, protocol: str, family: int) -> str:
        return f"{self.name}-{service:05d}-{protocol}-v{family}"

    @staticmethod
    def _socket(address: str, port: int, family: int) -> str:
        return socket(address, port, family)

    @staticmethod
    def vip(service: int, family: int) -> str:
        value = service + 1
        if family == 4:
            return f"100.0.{value >> 8 & 255}.{value & 255}"
        return f"100::{value:x}"

    def record_metric(self, iteration: object, phase: str, start: int) -> None:
        duration = time.time_ns() - start
        with self.metrics_file.open("a") as output:
            output.write(f"{iteration},{phase},{duration}\n")
        print(f"metric iteration={iteration} phase={phase} duration_ns={duration}")

    def measure(self, iteration: object, phase: str, action: Callable[[], T]) -> T:
        start = time.time_ns()
        result = action()
        self.record_metric(iteration, phase, start)
        return result

    def _destroy_named(self, table: str, name: str) -> None:
        output = self.runner.output(
            "ovn-nbctl",
            "--bare",
            "--columns=_uuid",
            "find",
            table,
            f"name={name}",
        )
        for uuid in output.split():
            self.runner.run("ovn-nbctl", "destroy", table, uuid)

    def create_namespace(self) -> None:
        if self.load_balancer_group:
            self.load_balancer_group_uuid = self._named_uuid(
                "Load_Balancer_Group",
                self.load_balancer_group,
            )
        for port_group in self.port_groups:
            self._destroy_named("Port_Group", port_group)
            self.runner.run("ovn-nbctl", "pg-add", port_group)
        for family, enabled in enumerate((self.ipv4_enabled, self.ipv6_enabled)):
            if not enabled:
                continue
            name = self.address_sets[family]
            self._destroy_named("Address_Set", name)
            address_set_id = self.runner.output(
                "ovn-nbctl",
                "create",
                "Address_Set",
                f"name={name}",
                f"external_ids:ovn-tmt-tests-owner={self.name}",
            )
            self.address_set_ids[family] = address_set_id

    def create_topology(self) -> None:
        if self.workers:
            raise RuntimeError("prepared scale topology is owned by provisioning")
        self._destroy_named("Logical_Switch", self.name)
        self.runner.run("ovn-nbctl", "ls-add", self.name)
        self.create_namespace()

    def add_endpoint(
        self,
        index: int,
        phase: str,
        passive: bool = False,
        converge: bool = True,
    ) -> dict[str, Any]:
        endpoint = self.endpoint(index)
        self.endpoints.append(endpoint)
        addresses = [endpoint["mac"]]
        if self.ipv4_enabled:
            addresses.append(endpoint["ipv4"])
        if self.ipv6_enabled:
            addresses.append(endpoint["ipv6"])

        start = time.time_ns()
        self.runner.run(
            "ovn-nbctl",
            "--may-exist",
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
        )
        for family, enabled in enumerate((self.ipv4_enabled, self.ipv6_enabled)):
            if enabled and self.address_set_ids[family] is not None:
                address = endpoint[f"ipv{family * 2 + 4}"]
                self.runner.run(
                    "ovn-nbctl",
                    "add",
                    "Address_Set",
                    self.address_set_ids[family],
                    "addresses",
                    f'"{address}"',
                )
        self.record_metric(index, f"{phase}_nb", start)

        start = time.time_ns()
        namespace = endpoint["namespace"]
        interface = endpoint["interface"]
        peer = f"{namespace}-n"
        ip = ("ip", "-n", namespace)
        commands = [
            _command("ovs-vsctl", "--if-exists", "del-port", "br-int", interface),
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
                        f"{endpoint['ipv4']}/{endpoint.get('prefix4', 16)}",
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
                        f"{endpoint['ipv6']}/{endpoint.get('prefix6', 64)}",
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
                "br-int",
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
            start = time.time_ns()
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

    def _replace_load_balancer(
        self,
        name: str,
        protocol: str,
        vips: Optional[Mapping[str, Sequence[str]]] = None,
        switches: Iterable[str] = (),
        routers: Iterable[str] = (),
        group: Optional[str] = None,
    ) -> None:
        self.load_balancers.append(name)
        replace(
            self.runner,
            self.name,
            name,
            protocol,
            vips,
            switches,
            routers,
            group,
        )

    def add_background_load_balancers(self, protocols: Sequence[str]) -> None:
        if not self.workers:
            raise RuntimeError("background load balancers need a scale topology")

        for family, enabled in (
            (4, self.ipv4_enabled),
            (6, self.ipv6_enabled),
        ):
            if not enabled:
                continue
            vip_network = ipaddress.ip_network("4.0.0.0/8" if family == 4 else "4::/32")
            backend_network = ipaddress.ip_network(
                "6.0.0.0/8" if family == 4 else "6::/32"
            )
            static_backends = [
                self._socket(str(backend_network[index]), 8080, family)
                for index in range(1, 3)
            ]
            vips = {
                self._socket(str(vip_network[index]), 80, family): list(static_backends)
                for index in range(1, 66)
            }
            first_vip = next(iter(vips))
            vips[first_vip].extend(
                self._socket(endpoint[f"ipv{family}"], 8080, family)
                for endpoint in self.endpoints
            )
            suffix = "" if family == 4 else "6"
            for protocol in protocols:
                self._replace_load_balancer(
                    f"lb-cluster1{suffix}-{protocol}",
                    protocol,
                    vips,
                    switches=(worker["switch"] for worker in self.workers),
                    routers=(worker["gateway_router"] for worker in self.workers),
                )
                for worker in self.workers:
                    self._replace_load_balancer(
                        f"lb-{worker['gateway_router']}{suffix}-{protocol}",
                        protocol,
                        routers=[worker["gateway_router"]],
                    )

    def add_service(self, service: int, backend: int, protocols: Sequence[str]) -> None:
        endpoint = self.endpoint(backend)
        group = None
        if self.load_balancer_group:
            if self.load_balancer_group_uuid is None:
                self.load_balancer_group_uuid = self._named_uuid(
                    "Load_Balancer_Group",
                    self.load_balancer_group,
                )
            group = self.load_balancer_group_uuid
        for protocol in protocols:
            for family, enabled in (
                (4, self.ipv4_enabled),
                (6, self.ipv6_enabled),
            ):
                if not enabled:
                    continue
                name = self.service_name(service, protocol, family)
                self._replace_load_balancer(
                    name,
                    protocol,
                    {
                        self._socket(self.vip(service, family), 80, family): [
                            self._socket(
                                endpoint[f"ipv{family}"],
                                8080,
                                family,
                            )
                        ]
                    },
                    switches=[] if group else [self.name],
                    group=group,
                )

    def verify_connectivity(
        self, index: int, target_index: Optional[int] = None
    ) -> None:
        source = self.endpoint(index)
        if target_index is None:
            target_index = (index % len(self.computes) + 1) % len(self.computes)
        target = self.endpoint(target_index)
        start = time.time_ns()
        for family, enabled in (
            (4, self.ipv4_enabled),
            (6, self.ipv6_enabled),
        ):
            if not enabled:
                continue
            destination = target[f"ipv{family}"]
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

    def _remove_endpoint(self, endpoint: dict[str, Any]) -> None:
        self.runner.run(
            "ovn-nbctl",
            "--if-exists",
            "lsp-del",
            endpoint["port"],
        )
        self.runner.run_many(
            [
                _command(
                    "ovs-vsctl",
                    "--if-exists",
                    "del-port",
                    "br-int",
                    endpoint["interface"],
                ),
                _command("ip", "link", "delete", endpoint["interface"], check=False),
                _command("ip", "netns", "delete", endpoint["namespace"], check=False),
            ],
            guest=endpoint["guest"],
        )
        endpoint["removed"] = True

    def remove_endpoint(self, endpoint: dict[str, Any]) -> None:
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
        start = time.time_ns()
        first_error = None

        def attempt(*command: object, **kwargs: Any) -> None:
            nonlocal first_error
            try:
                if command:
                    self.runner.run(*command, **kwargs)
                else:
                    kwargs["action"]()
            except Exception as error:
                if first_error is None:
                    first_error = error

        for endpoint in self.endpoints:
            if endpoint.get("removed"):
                continue
            attempt(action=lambda endpoint=endpoint: self._remove_endpoint(endpoint))
        for load_balancer in self.load_balancers:
            attempt("ovn-nbctl", "--if-exists", "lb-del", load_balancer)
        if not self.workers:
            attempt("ovn-nbctl", "--if-exists", "ls-del", self.name)
        for port_group in self.port_groups:
            attempt(
                action=lambda name=port_group: self._destroy_named("Port_Group", name)
            )
        for address_set in self.address_sets:
            attempt(
                action=lambda name=address_set: self._destroy_named("Address_Set", name)
            )
        attempt("ovn-nbctl", "--wait=hv", f"--timeout={self.sync_timeout}", "sync")
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
                f"name={name}",
            )
            if output:
                raise AssertionError(f"{table} remains after cleanup: {name}")

        guest_state = {}
        for guest in dict.fromkeys(endpoint["guest"] for endpoint in self.endpoints):
            namespaces = self.runner.output("ip", "netns", "list", guest=guest)
            ports = self.runner.output(
                "ovs-vsctl",
                "list-ports",
                "br-int",
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
