import ipaddress
import json
import subprocess
from typing import Any, Optional, Union


def _command(*parts: object, check: bool = True) -> tuple[tuple[object, ...], bool]:
    return parts, check


class Network:
    def __init__(self, runner: Any, guest: Optional[str] = None) -> None:
        self.runner = runner
        self.guest = guest

    def namespace_exists(self, namespace: str) -> bool:
        result = self.runner.namespace(namespace, "true", guest=self.guest, check=False)
        return result.returncode == 0

    def ping(
        self, namespace: str, destination: str, count: int = 1, timeout: int = 1
    ) -> bool:
        result = self.runner.namespace(
            namespace,
            "ping",
            "-q",
            "-c",
            count,
            "-W",
            timeout,
            destination,
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
            namespace,
            "ping",
            "-q",
            "-c",
            "1",
            "-W",
            "1",
            destination,
            guest=self.guest,
            attempts=attempts,
        )

    def link(self, interface: str, namespace: Optional[str] = None) -> Any:
        command = ["ip", "-j"]
        if namespace:
            command.extend(("-n", namespace))
        command.extend(("link", "show", "dev", interface))
        result = self.runner.run(*command, guest=self.guest, check=False)
        if result.returncode:
            return None
        links = json.loads(result.stdout)
        return links[0] if links else None

    def addresses(
        self,
        interface: str,
        namespace: Optional[str] = None,
        scope: Optional[str] = None,
    ) -> list[str]:
        command = ["ip", "-j"]
        if namespace:
            command.extend(("-n", namespace))
        command.extend(("address", "show", "dev", interface))
        links = json.loads(self.runner.output(*command, guest=self.guest))
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
        command = ["ip", "-j"]
        if namespace:
            command.extend(("-n", namespace))
        if family:
            command.append(f"-{family}")
        command.extend(("route", "show"))
        if table is not None:
            command.extend(("table", str(table)))
        if destination is not None:
            command.append(destination)
        result = self.runner.run(
            *command,
            guest=self.guest,
            check=False,
        )
        if result.returncode and "FIB table does not exist" not in result.stderr:
            result.check_returncode()
        return json.loads(result.stdout)


class ExternalPeers:
    def __init__(
        self,
        runner: Any,
        topology: dict[str, Any],
        ipv4: bool = True,
        ipv6: bool = True,
        mtu: int = 1500,
        timeout: int = 60,
        prefix: str = "dhe",
    ) -> None:
        self.runner = runner
        self.bridge = topology.get("physical_bridge")
        self.ipv4 = ipv4
        self.ipv6 = ipv6
        self.mtu = mtu
        self.timeout = timeout
        if not self.bridge:
            raise ValueError("scale topology does not contain a physical bridge")

        self.peers = {}
        for index, worker in enumerate(topology["workers"]):
            peer = {
                "guest": worker["chassis"],
                "namespace": f"{prefix}{index:05d}",
                "interface": f"{prefix}{index:05d}-p",
                "vlan": worker.get("external_vlan"),
            }
            if peer["vlan"] is not None and (
                isinstance(peer["vlan"], bool)
                or not isinstance(peer["vlan"], int)
                or not 1 <= peer["vlan"] <= 4094
            ):
                raise ValueError(
                    f"worker {worker['name']} external VLAN must be 1 through 4094"
                )
            for family, enabled in ((4, ipv4), (6, ipv6)):
                if not enabled:
                    continue
                network = ipaddress.ip_network(
                    worker.get("external", {}).get(f"ipv{family}", "")
                )
                if network.num_addresses < 4:
                    raise ValueError(
                        f"worker {worker['name']} external subnet is too small"
                    )
                peer[f"ipv{family}"] = str(network[-3])
                peer[f"gateway{family}"] = str(network[-2])
                peer[f"prefix{family}"] = network.prefixlen
            self.peers[worker["name"]] = peer

    def _remove_commands(
        self, peer: dict[str, Any]
    ) -> list[tuple[tuple[object, ...], bool]]:
        return [
            _command(
                "ovs-vsctl",
                "--if-exists",
                "del-port",
                self.bridge,
                peer["interface"],
            ),
            _command("ip", "link", "delete", peer["interface"], check=False),
            _command("ip", "netns", "delete", peer["namespace"], check=False),
        ]

    def create(self) -> None:
        for peer in self.peers.values():
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
            self.runner.run_many(commands, guest=peer["guest"])

    def verify(self, endpoint: dict[str, Any]) -> None:
        peer = self.peers[endpoint["worker"]]
        if peer["guest"] != endpoint["guest"]:
            raise ValueError("endpoint and external peer use different chassis")
        network = Network(self.runner, endpoint["guest"])
        for family, enabled in ((4, self.ipv4), (6, self.ipv6)):
            if enabled:
                network.wait_for_ping(
                    endpoint["namespace"],
                    peer[f"ipv{family}"],
                    attempts=self.timeout,
                )

    def cleanup(self) -> None:
        first_error = None
        for peer in self.peers.values():
            try:
                self.runner.run_many(
                    self._remove_commands(peer),
                    guest=peer["guest"],
                )
            except Exception as error:
                if first_error is None:
                    first_error = error
        if first_error is not None:
            raise first_error

    def verify_cleanup(self) -> None:
        for peer in self.peers.values():
            network = Network(self.runner, peer["guest"])
            if network.namespace_exists(peer["namespace"]):
                raise AssertionError(
                    f"external namespace remains after cleanup: {peer['namespace']}"
                )
            result = self.runner.run(
                "ovs-vsctl",
                "port-to-br",
                peer["interface"],
                guest=peer["guest"],
                check=False,
            )
            if result.returncode == 0:
                raise AssertionError(
                    f"external OVS port remains after cleanup: {peer['interface']}"
                )
