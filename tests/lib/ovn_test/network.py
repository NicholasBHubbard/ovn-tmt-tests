import hashlib
import ipaddress
import json
import re
import subprocess
from collections.abc import Mapping, Sequence
from typing import Any, Optional, Union

from ovn_test.command import Runner

_INTERFACE = re.compile(r"^[A-Za-z0-9_.-]+$")


def _command(*parts: object, check: bool = True) -> tuple[tuple[object, ...], bool]:
    return parts, check


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} must be a non-empty string")
    return value


def _positive(value: int, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{label} must be a positive integer")
    return value


def _family(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value not in (4, 6):
        raise ValueError("IP family must be 4 or 6")
    return value


def _rows(output: str, label: str) -> list[dict[str, Any]]:
    try:
        rows = json.loads(output)
    except (json.JSONDecodeError, TypeError) as error:
        raise RuntimeError(f"invalid JSON returned by {label}") from error
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise RuntimeError(f"invalid rows returned by {label}")
    return rows


def _namespace(command: list[object], namespace: Optional[str]) -> None:
    if namespace is not None:
        command.extend(("-n", _text(namespace, "network namespace")))


class Network:
    def __init__(self, runner: Runner, guest: Optional[str] = None) -> None:
        self.runner = runner
        self.guest = None if guest is None else _text(guest, "guest")

    def namespace_exists(self, namespace: str) -> bool:
        result = self.runner.namespace(
            _text(namespace, "network namespace"),
            "true",
            guest=self.guest,
            check=False,
        )
        return result.returncode == 0

    def ping(
        self, namespace: str, destination: str, count: int = 1, timeout: int = 1
    ) -> bool:
        result = self.runner.namespace(
            _text(namespace, "network namespace"),
            "ping",
            "-q",
            "-c",
            _positive(count, "ping count"),
            "-W",
            _positive(timeout, "ping timeout"),
            _text(destination, "ping destination"),
            guest=self.guest,
            check=False,
        )
        return result.returncode == 0

    def wait_for_ping(
        self, namespace: str, destination: str, attempts: int = 30
    ) -> subprocess.CompletedProcess[str]:
        return self.runner.wait(
            "ip",
            "netns",
            "exec",
            _text(namespace, "network namespace"),
            "ping",
            "-q",
            "-c",
            "1",
            "-W",
            "1",
            _text(destination, "ping destination"),
            guest=self.guest,
            attempts=_positive(attempts, "ping attempts"),
        )

    def link(
        self, interface: str, namespace: Optional[str] = None
    ) -> Optional[dict[str, Any]]:
        command: list[object] = ["ip", "-j"]
        _namespace(command, namespace)
        command.extend(("link", "show", "dev", _text(interface, "interface")))
        result = self.runner.run(*command, guest=self.guest, check=False)
        if result.returncode:
            return None
        links = _rows(result.stdout, "ip link")
        return links[0] if links else None

    def require_link(
        self, interface: str, namespace: Optional[str] = None
    ) -> dict[str, Any]:
        link = self.link(interface, namespace)
        if link is None:
            raise AssertionError(f"network interface does not exist: {interface}")
        return link

    def addresses(
        self,
        interface: str,
        namespace: Optional[str] = None,
        scope: Optional[str] = None,
    ) -> list[str]:
        if scope is not None:
            scope = _text(scope, "address scope")
        command: list[object] = ["ip", "-j"]
        _namespace(command, namespace)
        command.extend(("address", "show", "dev", _text(interface, "interface")))
        links = _rows(
            self.runner.output(*command, guest=self.guest),
            "ip address",
        )
        return [
            f"{address['local']}/{address['prefixlen']}"
            for link in links
            for address in link.get("addr_info", [])
            if scope is None or address.get("scope") == scope
        ]

    def routes(
        self,
        namespace: Optional[str] = None,
        family: Optional[int] = None,
        table: Optional[Union[int, str]] = None,
        destination: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        command: list[object] = ["ip", "-j"]
        _namespace(command, namespace)
        if family is not None:
            command.append(f"-{_family(family)}")
        command.extend(("route", "show"))
        if table is not None:
            if isinstance(table, bool) or not isinstance(table, (int, str)):
                raise ValueError("route table must be a non-negative integer or name")
            if isinstance(table, int) and not 0 <= table <= 4294967295:
                raise ValueError("route table must be a non-negative integer or name")
            command.extend(
                (
                    "table",
                    _text(table, "route table")
                    if isinstance(table, str)
                    else str(table),
                )
            )
        if destination is not None:
            command.append(_text(destination, "route destination"))
        result = self.runner.run(*command, guest=self.guest, check=False)
        try:
            routes = _rows(result.stdout, "ip route")
        except RuntimeError:
            if result.returncode:
                result.check_returncode()
            raise
        if result.returncode:
            if table is not None and result.returncode == 2 and not routes:
                return []
            result.check_returncode()
        return routes


class ExternalPeers:
    def __init__(
        self,
        runner: Runner,
        topology: Mapping[str, Any],
        ipv4: bool = True,
        ipv6: bool = True,
        mtu: int = 1500,
        timeout: int = 60,
        prefix: str = "dhe",
    ) -> None:
        if not isinstance(topology, Mapping):
            raise ValueError("scale topology must be a mapping")
        if (
            not isinstance(ipv4, bool)
            or not isinstance(ipv6, bool)
            or not (ipv4 or ipv6)
        ):
            raise ValueError("at least one boolean IP family setting must be enabled")
        minimum_mtu = 1280 if ipv6 else 68
        if (
            isinstance(mtu, bool)
            or not isinstance(mtu, int)
            or not (minimum_mtu <= mtu <= 65535)
        ):
            raise ValueError(f"MTU must be between {minimum_mtu} and 65535")
        prefix = _text(prefix, "external peer prefix")
        if _INTERFACE.fullmatch(prefix) is None:
            raise ValueError(
                "external peer prefix contains invalid interface characters"
            )
        if len(prefix) > 5:
            raise ValueError("external peer prefix must be at most five characters")
        workers = topology.get("workers")
        if (
            isinstance(workers, (str, bytes))
            or not isinstance(workers, Sequence)
            or not workers
        ):
            raise ValueError("scale topology must contain at least one worker")

        self.runner = runner
        self.bridge = _text(topology.get("physical_bridge"), "physical bridge")
        self.ipv4 = ipv4
        self.ipv6 = ipv6
        self.mtu = mtu
        self.timeout = _positive(timeout, "external peer timeout")
        self.peers: dict[str, dict[str, Any]] = {}
        resource_names = set()

        for worker in workers:
            if not isinstance(worker, Mapping):
                raise ValueError("each scale topology worker must be a mapping")
            name = _text(worker.get("name"), "worker name")
            if name in self.peers:
                raise ValueError(f"scale topology worker is duplicated: {name}")
            suffix = hashlib.sha256(name.encode()).hexdigest()[:8]
            namespace = f"{prefix}{suffix}"
            interface = f"{namespace}-p"
            if interface in resource_names:
                raise ValueError("external peer resource name is not unique")
            resource_names.add(interface)
            peer = {
                "guest": _text(worker.get("chassis"), f"worker {name} chassis"),
                "namespace": namespace,
                "interface": interface,
                "vlan": worker.get("external_vlan"),
            }
            if peer["vlan"] is not None and (
                isinstance(peer["vlan"], bool)
                or not isinstance(peer["vlan"], int)
                or not 1 <= peer["vlan"] <= 4094
            ):
                raise ValueError(f"worker {name} external VLAN must be 1 through 4094")
            external = worker.get("external")
            if not isinstance(external, Mapping):
                raise ValueError(f"worker {name} external networks must be a mapping")
            for family, enabled in ((4, ipv4), (6, ipv6)):
                if not enabled:
                    continue
                value = _text(
                    external.get(f"ipv{family}"),
                    f"worker {name} external IPv{family} subnet",
                )
                try:
                    network = ipaddress.ip_network(value)
                except ValueError as error:
                    raise ValueError(
                        f"worker {name} has an invalid external IPv{family} subnet"
                    ) from error
                if network.version != family:
                    raise ValueError(
                        f"worker {name} external subnet must be IPv{family}"
                    )
                if network.num_addresses < 4:
                    raise ValueError(f"worker {name} external subnet is too small")
                peer[f"ipv{family}"] = str(network[-3])
                peer[f"gateway{family}"] = str(network[-2])
                peer[f"prefix{family}"] = network.prefixlen
            self.peers[name] = peer

    def _remove_commands(
        self, peer: Mapping[str, Any]
    ) -> list[tuple[tuple[object, ...], bool]]:
        return [
            _command(
                "ovs-vsctl",
                "--if-exists",
                "del-port",
                peer["interface"],
                check=False,
            ),
            _command("ip", "link", "delete", peer["interface"], check=False),
            _command("ip", "netns", "delete", peer["namespace"], check=False),
        ]

    def _create_commands(
        self, peer: Mapping[str, Any]
    ) -> list[tuple[tuple[object, ...], bool]]:
        namespace = peer["namespace"]
        interface = peer["interface"]
        namespace_interface = f"{namespace}-n"
        namespace_ip = ("ip", "-n", namespace)
        commands = [
            *self._remove_commands(peer),
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
                namespace_interface,
            ),
            _command(
                "ip",
                "link",
                "set",
                namespace_interface,
                "netns",
                namespace,
            ),
            _command(
                *namespace_ip,
                "link",
                "set",
                namespace_interface,
                "name",
                "eth0",
            ),
            _command("ip", "link", "set", interface, "mtu", self.mtu, "up"),
            _command(*namespace_ip, "link", "set", "lo", "up"),
            _command(
                *namespace_ip,
                "link",
                "set",
                "eth0",
                "mtu",
                self.mtu,
                "up",
            ),
        ]
        for family, enabled in ((4, self.ipv4), (6, self.ipv6)):
            if not enabled:
                continue
            commands.extend(
                [
                    _command(
                        *namespace_ip,
                        *(("-6",) if family == 6 else ()),
                        "address",
                        "replace",
                        f"{peer[f'ipv{family}']}/{peer[f'prefix{family}']}",
                        "dev",
                        "eth0",
                        *(("nodad",) if family == 6 else ()),
                    ),
                    _command(
                        *namespace_ip,
                        *(("-6",) if family == 6 else ()),
                        "route",
                        "replace",
                        "default",
                        "via",
                        peer[f"gateway{family}"],
                    ),
                ]
            )
        commands.append(
            _command(
                "ovs-vsctl",
                "--may-exist",
                "add-port",
                self.bridge,
                interface,
                "--",
                "set",
                "Port",
                interface,
                f"tag={peer['vlan'] if peer['vlan'] is not None else '[]'}",
            )
        )
        return commands

    def _guest_commands(
        self, create: bool
    ) -> dict[str, list[tuple[tuple[object, ...], bool]]]:
        batches: dict[str, list[tuple[tuple[object, ...], bool]]] = {}
        for peer in self.peers.values():
            commands = (
                self._create_commands(peer) if create else self._remove_commands(peer)
            )
            batches.setdefault(peer["guest"], []).extend(commands)
        return batches

    def create(self) -> None:
        for guest, commands in self._guest_commands(create=True).items():
            self.runner.run_many(commands, guest=guest)

    def _peer(self, endpoint: Mapping[str, object]) -> dict[str, Any]:
        if not isinstance(endpoint, Mapping):
            raise ValueError("endpoint must be a mapping")
        worker = _text(endpoint.get("worker"), "endpoint worker")
        guest = _text(endpoint.get("guest"), "endpoint guest")
        peer = self.peers.get(worker)
        if peer is None:
            raise ValueError(f"endpoint references unknown worker: {worker}")
        if peer["guest"] != guest:
            raise ValueError("endpoint and external peer use different chassis")
        return peer

    @staticmethod
    def _endpoint_address(endpoint: Mapping[str, object], family: int) -> str:
        value = _text(endpoint.get(f"ipv{family}"), f"endpoint IPv{family} address")
        try:
            address = ipaddress.ip_address(value)
        except ValueError as error:
            raise ValueError(f"endpoint has an invalid IPv{family} address") from error
        if address.version != family:
            raise ValueError(f"endpoint address must be IPv{family}")
        return str(address)

    def address(self, endpoint: Mapping[str, object], family: int) -> str:
        family = _family(family)
        if not (self.ipv4 if family == 4 else self.ipv6):
            raise ValueError(f"IPv{family} external peers are disabled")
        return self._peer(endpoint)[f"ipv{family}"]

    def verify(self, endpoint: Mapping[str, object]) -> None:
        peer = self._peer(endpoint)
        namespace = _text(endpoint.get("namespace"), "endpoint network namespace")
        network = Network(self.runner, peer["guest"])
        for family, enabled in ((4, self.ipv4), (6, self.ipv6)):
            if enabled:
                network.wait_for_ping(
                    namespace,
                    peer[f"ipv{family}"],
                    attempts=self.timeout,
                )

    def verify_inbound(self, endpoint: Mapping[str, object]) -> None:
        peer = self._peer(endpoint)
        network = Network(self.runner, peer["guest"])
        for family, enabled in ((4, self.ipv4), (6, self.ipv6)):
            if enabled:
                network.wait_for_ping(
                    peer["namespace"],
                    self._endpoint_address(endpoint, family),
                    attempts=self.timeout,
                )

    def cleanup(self) -> None:
        first_error = None
        for guest, commands in self._guest_commands(create=False).items():
            try:
                self.runner.run_many(commands, guest=guest)
            except Exception as error:
                if first_error is None:
                    first_error = error
        if first_error is not None:
            raise first_error

    def verify_cleanup(self) -> None:
        peers_by_guest: dict[str, list[dict[str, Any]]] = {}
        for peer in self.peers.values():
            peers_by_guest.setdefault(peer["guest"], []).append(peer)
        for guest, peers in peers_by_guest.items():
            namespaces = {
                line.split()[0]
                for line in self.runner.output(
                    "ip", "netns", "list", guest=guest
                ).splitlines()
                if line.split()
            }
            interfaces = {
                line.strip().strip('"')
                for line in self.runner.output(
                    "ovs-vsctl",
                    "--data=bare",
                    "--no-headings",
                    "--columns=name",
                    "list",
                    "Interface",
                    guest=guest,
                ).splitlines()
                if line.strip()
            }
            for peer in peers:
                if peer["namespace"] in namespaces:
                    raise AssertionError(
                        f"external namespace remains after cleanup: {peer['namespace']}"
                    )
                if peer["interface"] in interfaces:
                    raise AssertionError(
                        f"external OVS port remains after cleanup: {peer['interface']}"
                    )
