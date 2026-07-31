import ipaddress
import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Callable

from ovn_test.command import Runner
from ovn_test.load_balancer import replace, socket

VALID_PROTOCOLS = {"tcp", "udp", "sctp"}


@dataclass
class _NamespaceGroup:
    port_group: str
    address_sets: dict[int, str]
    address_set_ids: dict[int, str] = field(default_factory=dict)
    ready: bool = False


def validate_cluster_density(
    startup: int,
    total: int,
    build_pods: int,
    test_pods: int,
    protocols: Sequence[str],
    timeout: int,
    ipv4: bool,
    ipv6: bool,
    mtu: int,
    chassis: int,
    workers: int,
    base_pods: int,
) -> None:
    positive = {
        "total namespaces": total,
        "test pods per namespace": test_pods,
        "timeout": timeout,
        "chassis": chassis,
        "workers": workers,
    }
    if any(
        isinstance(value, bool) or not isinstance(value, int) or value < 1
        for value in positive.values()
    ):
        raise ValueError(
            "namespace, pod, timeout, chassis and worker counts must be positive"
        )
    if any(
        isinstance(value, bool) or not isinstance(value, int) or value < 0
        for value in (startup, build_pods, base_pods)
    ):
        raise ValueError("startup, build pod and base pod counts must be non-negative")
    if startup > total:
        raise ValueError("startup namespaces cannot exceed total namespaces")
    if test_pods < 4:
        raise ValueError(
            "cluster density requires at least four test pods per namespace"
        )
    if chassis < 2:
        raise ValueError("cluster density requires at least two compute chassis")
    if not isinstance(ipv4, bool) or not isinstance(ipv6, bool) or not (ipv4 or ipv6):
        raise ValueError("at least one boolean IP family setting must be enabled")
    minimum_mtu = 1280 if ipv6 else 576
    if not minimum_mtu <= mtu <= 65535:
        raise ValueError(f"MTU must be between {minimum_mtu} and 65535")
    if not protocols or len(protocols) != len(set(protocols)):
        raise ValueError("load-balancer protocols must be unique")
    if set(protocols) - VALID_PROTOCOLS:
        raise ValueError("load-balancer protocols must be tcp, udp or sctp")
    endpoint_count = total * test_pods + (total - startup) * build_pods
    if endpoint_count > 65534:
        raise ValueError("cluster density exceeds its endpoint identity space")


class OvnNamespace:
    def __init__(
        self,
        runner: Runner,
        owner: str,
        name: str,
        index: int,
        ipv4: bool = True,
        ipv6: bool = True,
    ) -> None:
        self.runner = runner
        self.owner = owner
        self.name = name
        self.index = index
        self.ipv4 = ipv4
        self.ipv6 = ipv6
        self.port_group = f"pg_{name}"
        self.ingress_deny_group = f"pg_deny_igr_{name}"
        self.egress_deny_group = f"pg_deny_egr_{name}"
        self.port_groups = [
            self.port_group,
            self.ingress_deny_group,
            self.egress_deny_group,
        ]
        self.address_sets = {
            4: f"as_{name}",
            6: f"as6_{name}",
        }
        self.address_set_ids: dict[int, str] = {}
        self.groups: dict[str, _NamespaceGroup] = {}
        self.load_balancers: list[str] = []
        self.endpoints: list[dict[str, Any]] = []
        self.acls: dict[str, tuple[str, str, int, str, str]] = {}
        self.enforcing = False
        self.cleaned = False

    def _destroy_named(self, table: str, name: str) -> None:
        output = self.runner.output(
            "ovn-nbctl",
            "--bare",
            "--columns=_uuid",
            "find",
            table,
            f"name={json.dumps(name)}",
        )
        for uuid in output.split():
            self.runner.run("ovn-nbctl", "destroy", table, uuid)

    def _create_port_group(self, name: str) -> None:
        self._destroy_named("Port_Group", name)
        self.runner.run(
            "ovn-nbctl",
            "pg-add",
            name,
            "--",
            "set",
            "Port_Group",
            name,
            f"external_ids:ovn-tmt-tests-owner={json.dumps(self.owner)}",
        )

    def _create_address_set(self, name: str) -> str:
        self._destroy_named("Address_Set", name)
        return self.runner.output(
            "ovn-nbctl",
            "create",
            "Address_Set",
            f"name={json.dumps(name)}",
            f"external_ids:ovn-tmt-tests-owner={json.dumps(self.owner)}",
        )

    def create(self) -> None:
        for name in self.port_groups:
            self._create_port_group(name)
        for family, enabled in ((4, self.ipv4), (6, self.ipv6)):
            if not enabled:
                continue
            name = self.address_sets[family]
            self.address_set_ids[family] = self._create_address_set(name)

    def add_endpoints(self, endpoints: Sequence[dict[str, Any]]) -> None:
        for family, enabled in ((4, self.ipv4), (6, self.ipv6)):
            if not enabled:
                continue
            self.runner.run(
                "ovn-nbctl",
                "add",
                "Address_Set",
                self.address_set_ids[family],
                "addresses",
                *(json.dumps(endpoint[f"ipv{family}"]) for endpoint in endpoints),
            )
        self.endpoints.extend(endpoints)
        if self.enforcing:
            self._set_policy_ports()

    def _set_policy_ports(self) -> None:
        ports = list(dict.fromkeys(endpoint["port"] for endpoint in self.endpoints))
        for port_group in self.port_groups:
            self.runner.run(
                "ovn-nbctl",
                "pg-set-ports",
                port_group,
                *ports,
            )

    def enforce(self) -> None:
        if self.enforcing:
            return
        self._set_policy_ports()
        self.enforcing = True

    def _ip_family(self, family: int) -> str:
        if family not in (4, 6):
            raise ValueError("IP family must be 4 or 6")
        if not (self.ipv4 if family == 4 else self.ipv6):
            raise ValueError(f"IPv{family} is disabled for namespace {self.name}")
        return f"ip{family}"

    def _set_acl(
        self,
        name: str,
        target: str,
        direction: str,
        priority: int,
        match: str,
        action: str,
    ) -> None:
        acl = (target, direction, priority, match, action)
        previous = self.acls.get(name)
        if previous is not None and previous != acl:
            self.runner.run(
                "ovn-nbctl",
                "--type=port-group",
                "acl-del",
                *previous[:-1],
            )
        self.runner.run(
            "ovn-nbctl",
            "--type=port-group",
            "--may-exist",
            "acl-add",
            target,
            direction,
            priority,
            match,
            action,
        )
        self.acls[name] = acl

    def default_deny(
        self,
        family: int,
        priority: int = 1,
        control_priority: int = 2,
    ) -> None:
        network = self._ip_family(family)
        self.enforce()
        address_set = self.address_sets[family]
        for name, target, address, port in (
            ("ingress", self.ingress_deny_group, "src", "outport"),
            ("egress", self.egress_deny_group, "dst", "inport"),
        ):
            self._set_acl(
                f"deny-{family}-{name}",
                target,
                "to-lport",
                priority,
                f"{network}.{address} == ${address_set} && {port} == @{target}",
                "drop",
            )
            self._set_acl(
                f"allow-control-{family}-{name}",
                target,
                "to-lport",
                control_priority,
                f"{port} == @{target} && {'arp' if family == 4 else 'nd'}",
                "allow",
            )

    def allow_within(self, family: int, priority: int = 3) -> None:
        network = self._ip_family(family)
        self.enforce()
        address_set = self.address_sets[family]
        for name, address, port in (
            ("ingress", "src", "outport"),
            ("egress", "dst", "inport"),
        ):
            self._set_acl(
                f"allow-within-{family}-{name}",
                self.port_group,
                "to-lport",
                priority,
                f"{network}.{address} == ${address_set} && "
                f"{port} == @{self.port_group}",
                "allow-related",
            )

    def allow_to(
        self,
        other: "OvnNamespace",
        family: int,
        priority: int = 3,
    ) -> None:
        network = self._ip_family(family)
        other._ip_family(family)
        self.enforce()
        other.enforce()
        other._set_acl(
            f"allow-from-{family}-{self.name}",
            other.port_group,
            "to-lport",
            priority,
            f"{network}.src == ${self.address_sets[family]} && "
            f"outport == @{other.port_group}",
            "allow-related",
        )
        self._set_acl(
            f"allow-to-{family}-{other.name}",
            self.port_group,
            "to-lport",
            priority,
            f"{network}.dst == ${other.address_sets[family]} && "
            f"inport == @{self.port_group}",
            "allow-related",
        )

    def set_group(self, name: str, endpoints: Sequence[dict[str, Any]]) -> None:
        if not name:
            raise ValueError("namespace group name cannot be empty")
        ports = list(dict.fromkeys(endpoint["port"] for endpoint in endpoints))
        addresses = {
            family: list(
                dict.fromkeys(endpoint[f"ipv{family}"] for endpoint in endpoints)
            )
            for family, enabled in ((4, self.ipv4), (6, self.ipv6))
            if enabled
        }
        group = self.groups.get(name)
        if group is None:
            suffix = f"{self.name}_{len(self.groups)}"
            group = _NamespaceGroup(
                port_group=f"sub_pg_{suffix}",
                address_sets={
                    family: f"sub_as{'6' if family == 6 else ''}_{suffix}"
                    for family in addresses
                },
            )
            self.groups[name] = group
        if not group.ready:
            self._create_port_group(group.port_group)
            for family, address_set in group.address_sets.items():
                group.address_set_ids[family] = self._create_address_set(address_set)
            group.ready = True

        self.runner.run("ovn-nbctl", "pg-set-ports", group.port_group, *ports)
        for family, values in addresses.items():
            address_set_id = group.address_set_ids[family]
            self.runner.run(
                "ovn-nbctl",
                "clear",
                "Address_Set",
                address_set_id,
                "addresses",
            )
            if values:
                self.runner.run(
                    "ovn-nbctl",
                    "add",
                    "Address_Set",
                    address_set_id,
                    "addresses",
                    *(json.dumps(value) for value in values),
                )

    def allow_between(
        self,
        source: str,
        target: str,
        family: int,
        priority: int = 3,
    ) -> None:
        network = self._ip_family(family)
        try:
            source_group = self.groups[source]
            target_group = self.groups[target]
        except KeyError as error:
            raise ValueError(
                f"namespace group does not exist: {error.args[0]}"
            ) from error
        self.enforce()
        self._set_acl(
            f"allow-group-{family}-{source}-{target}-ingress",
            self.port_group,
            "to-lport",
            priority,
            f"{network}.src == ${source_group.address_sets[family]} && "
            f"outport == @{target_group.port_group}",
            "allow-related",
        )
        self._set_acl(
            f"allow-group-{family}-{source}-{target}-egress",
            self.port_group,
            "to-lport",
            priority,
            f"{network}.dst == ${target_group.address_sets[family]} && "
            f"inport == @{source_group.port_group}",
            "allow-related",
        )

    def allow_external(
        self,
        addresses: Sequence[str],
        family: int = 4,
        name: str = "external",
        priority: int = 3,
    ) -> None:
        network = self._ip_family(family)
        if not name:
            raise ValueError("external policy name cannot be empty")
        parsed = [ipaddress.ip_address(value) for value in addresses]
        if any(address.version != family for address in parsed):
            raise ValueError(f"external addresses must be IPv{family}")
        normalized = list(dict.fromkeys(str(address) for address in parsed))
        if not normalized:
            raise ValueError("external policy needs at least one address")
        self.enforce()
        self._set_acl(
            f"allow-{name}-{family}",
            self.port_group,
            "to-lport",
            priority,
            f"{network}.src == {{{','.join(normalized)}}} && "
            f"outport == @{self.port_group}",
            "allow-related",
        )

    def _vip(self, family: int, position: int) -> str:
        network = ipaddress.ip_network("30.0.0.0/16" if family == 4 else "30::/32")
        address = (
            int(network.network_address)
            + (self.index + 1) * network.num_addresses
            + position
            + 1
        )
        return str(ipaddress.ip_address(address))

    def add_services(
        self,
        endpoints: Sequence[dict[str, Any]],
        protocols: Sequence[str],
        group: str,
    ) -> None:
        if len(endpoints) < 4:
            raise ValueError("namespace services require at least four endpoints")
        backend_groups = [endpoints[:2], endpoints[2:3], endpoints[3:]]
        vips = {}
        for family, enabled in ((4, self.ipv4), (6, self.ipv6)):
            if not enabled:
                continue
            for position, backends in enumerate(backend_groups):
                vips[socket(self._vip(family, position), 80, family)] = [
                    socket(endpoint[f"ipv{family}"], 8080, family)
                    for endpoint in backends
                ]
        for protocol in protocols:
            name = f"lb_{self.name}-{protocol}"
            self.load_balancers.append(name)
            replace(
                self.runner,
                self.owner,
                name,
                protocol,
                vips,
                group=group,
            )

    def cleanup(self) -> None:
        if self.cleaned:
            return
        first_error = None

        def attempt(action: Callable[[], object]) -> None:
            nonlocal first_error
            try:
                action()
            except Exception as error:
                if first_error is None:
                    first_error = error

        for name in self.load_balancers:
            attempt(
                lambda name=name: self.runner.run(
                    "ovn-nbctl",
                    "--if-exists",
                    "lb-del",
                    name,
                )
            )
        for group in self.groups.values():
            attempt(
                lambda group=group: self._destroy_named("Port_Group", group.port_group)
            )
            for address_set in group.address_sets.values():
                attempt(
                    lambda address_set=address_set: self._destroy_named(
                        "Address_Set", address_set
                    )
                )
        for name in self.port_groups:
            attempt(lambda name=name: self._destroy_named("Port_Group", name))
        for family, name in self.address_sets.items():
            if (family == 4 and self.ipv4) or (family == 6 and self.ipv6):
                attempt(lambda name=name: self._destroy_named("Address_Set", name))
        self.cleaned = first_error is None
        if first_error is not None:
            raise first_error

    def verify_cleanup(self) -> None:
        for table, names in (
            ("Load_Balancer", self.load_balancers),
            (
                "Port_Group",
                [
                    *self.port_groups,
                    *(group.port_group for group in self.groups.values()),
                ],
            ),
            (
                "Address_Set",
                [
                    *(
                        name
                        for family, name in self.address_sets.items()
                        if (family == 4 and self.ipv4) or (family == 6 and self.ipv6)
                    ),
                    *(
                        name
                        for group in self.groups.values()
                        for name in group.address_sets.values()
                    ),
                ],
            ),
        ):
            for name in names:
                output = self.runner.output(
                    "ovn-nbctl",
                    "--bare",
                    "--columns=name",
                    "find",
                    table,
                    f"name={json.dumps(name)}",
                )
                if output:
                    raise AssertionError(f"{table} remains after cleanup: {name}")
