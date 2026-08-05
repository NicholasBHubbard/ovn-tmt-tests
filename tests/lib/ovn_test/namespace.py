import csv
import hashlib
import ipaddress
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from io import StringIO
from typing import Callable, Optional

from ovn_test.command import Runner
from ovn_test.load_balancer import DEFAULT_OPTIONS, Backends, LoadBalancers

_NAME = re.compile(r"^[A-Za-z_.][A-Za-z_.0-9]*$")
_RESOURCE_TABLES = {"Address_Set", "Port_Group"}
_Acl = tuple[str, str, int, str, str]


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} must be a non-empty string")
    return value


def _priority(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 32767:
        raise ValueError("ACL priority must be an integer between 0 and 32767")
    return value


class NamespaceResources:
    """Owner-scoped OVN resources shared by a set of namespaces."""

    def __init__(self, runner: Runner, owner: str) -> None:
        self.runner = runner
        self.owner = _text(owner, "owner")
        self.load_balancers = LoadBalancers(runner, owner)
        self._resources: dict[str, Optional[dict[str, str]]] = {
            table: None for table in _RESOURCE_TABLES
        }

    def _load(self, table: str) -> dict[str, str]:
        resources = self._resources[table]
        if resources is not None:
            return resources
        output = self.runner.output(
            "ovn-nbctl",
            "--format=csv",
            "--data=bare",
            "--no-headings",
            "--columns=_uuid,name",
            "find",
            table,
            f"external_ids:ovn-tmt-tests-owner={json.dumps(self.owner)}",
        )
        resources = {}
        for row in csv.reader(StringIO(output)):
            if len(row) != 2:
                raise RuntimeError(f"invalid {table} inventory returned by OVN")
            uuid, name = row
            if name in resources:
                raise RuntimeError(f"{table} {self.owner}/{name} is not unique")
            resources[name] = uuid
        self._resources[table] = resources
        return resources

    def ensure(self, table: str, name: str) -> str:
        if table not in _RESOURCE_TABLES:
            raise ValueError(f"unsupported namespace resource table: {table}")
        name = _text(name, f"{table} name")
        resources = self._load(table)
        uuid = resources.get(name)
        if uuid is not None:
            return uuid
        output = self.runner.output(
            "ovn-nbctl",
            "create",
            table,
            f"name={json.dumps(name)}",
            f"external_ids:ovn-tmt-tests-owner={json.dumps(self.owner)}",
        )
        created = output.split()
        if len(created) != 1:
            raise RuntimeError(f"OVN did not return one {table} UUID")
        resources[name] = created[0]
        return created[0]

    def delete(self, table: str, name: str) -> None:
        if table not in _RESOURCE_TABLES:
            raise ValueError(f"unsupported namespace resource table: {table}")
        resources = self._load(table)
        uuid = resources.get(name)
        if uuid is not None:
            self.runner.run("ovn-nbctl", "destroy", table, uuid)
            del resources[name]

    def contains(self, table: str, name: str) -> bool:
        if table not in _RESOURCE_TABLES:
            raise ValueError(f"unsupported namespace resource table: {table}")
        return name in self._load(table)


@dataclass
class _NamespaceGroup:
    port_group: str
    address_sets: dict[int, str]
    address_set_ids: dict[int, str] = field(default_factory=dict)
    ports: tuple[str, ...] = ()
    addresses: dict[int, tuple[str, ...]] = field(default_factory=dict)
    ready: bool = False


class OvnNamespace:
    def __init__(
        self,
        runner: Runner,
        owner: str,
        name: str,
        index: int,
        ipv4: bool = True,
        ipv6: bool = True,
        resources: Optional[NamespaceResources] = None,
    ) -> None:
        if not isinstance(name, str) or _NAME.fullmatch(name) is None:
            raise ValueError("namespace name must be a valid OVN identifier")
        if isinstance(index, bool) or not isinstance(index, int) or index < 0:
            raise ValueError("namespace index must be a non-negative integer")
        if (
            not isinstance(ipv4, bool)
            or not isinstance(ipv6, bool)
            or not (ipv4 or ipv6)
        ):
            raise ValueError("at least one boolean IP family setting must be enabled")
        owner = _text(owner, "owner")
        if resources is not None and (
            resources.runner is not runner or resources.owner != owner
        ):
            raise ValueError("namespace resources must use the same runner and owner")

        self.runner = runner
        self.owner = owner
        self.name = name
        self.index = index
        self.ipv4 = ipv4
        self.ipv6 = ipv6
        self.resources = resources or NamespaceResources(runner, owner)
        self.port_group = f"pg_{name}"
        self.ingress_deny_group = f"pg_deny_igr_{name}"
        self.egress_deny_group = f"pg_deny_egr_{name}"
        self.port_groups = [
            self.port_group,
            self.ingress_deny_group,
            self.egress_deny_group,
        ]
        self.address_sets = {4: f"as_{name}", 6: f"as6_{name}"}
        self.address_set_ids: dict[int, str] = {}
        self.groups: dict[str, _NamespaceGroup] = {}
        self.load_balancers: list[str] = []
        self.endpoints: list[dict[str, str]] = []
        self.acls: dict[str, _Acl] = {}
        self.enforcing = False
        self.created = False
        self.cleaned = False

    def _enabled_families(self) -> tuple[int, ...]:
        return tuple(
            family for family, enabled in ((4, self.ipv4), (6, self.ipv6)) if enabled
        )

    def _require_created(self) -> None:
        if not self.created:
            raise RuntimeError(f"namespace {self.name} has not been created")
        if self.cleaned:
            raise RuntimeError(f"cleaned namespace {self.name} cannot be reused")

    def _normalize_endpoints(
        self, endpoints: Sequence[Mapping[str, object]]
    ) -> list[dict[str, str]]:
        if isinstance(endpoints, (str, bytes)) or not isinstance(endpoints, Sequence):
            raise ValueError("endpoints must be a sequence of mappings")
        normalized = []
        ports = set()
        for endpoint in endpoints:
            if not isinstance(endpoint, Mapping):
                raise ValueError("each endpoint must be a mapping")
            port = _text(endpoint.get("port"), "endpoint port")
            if port in ports:
                raise ValueError(f"endpoint port is duplicated: {port}")
            ports.add(port)
            item = {"port": port}
            for family in self._enabled_families():
                value = _text(endpoint.get(f"ipv{family}"), f"endpoint IPv{family}")
                try:
                    address = ipaddress.ip_address(value)
                except ValueError as error:
                    raise ValueError(
                        f"invalid endpoint IPv{family} address: {value}"
                    ) from error
                if address.version != family:
                    raise ValueError(f"endpoint address must be IPv{family}: {value}")
                item[f"ipv{family}"] = str(address)
            normalized.append(item)
        return normalized

    def create(self) -> None:
        if self.cleaned:
            raise RuntimeError(f"cleaned namespace {self.name} cannot be reused")
        for name in self.port_groups:
            self.resources.ensure("Port_Group", name)
        for family in self._enabled_families():
            name = self.address_sets[family]
            self.address_set_ids[family] = self.resources.ensure("Address_Set", name)
        self.created = True
        self._reset_acls()
        self._apply_endpoints()
        for acl in self.acls.values():
            self._write_acl(acl)

    @staticmethod
    def _operation(command: list[object], *operation: object) -> None:
        if len(command) > 1:
            command.append("--")
        command.extend(operation)

    def _apply_endpoints(
        self,
        endpoints: Optional[Sequence[Mapping[str, str]]] = None,
        enforcing: Optional[bool] = None,
    ) -> None:
        self._require_created()
        desired = self.endpoints if endpoints is None else endpoints
        apply_ports = self.enforcing if enforcing is None else enforcing
        command: list[object] = ["ovn-nbctl"]
        ports = tuple(endpoint["port"] for endpoint in desired)
        for port_group in self.port_groups:
            if apply_ports and ports:
                self._operation(command, "pg-set-ports", port_group, *ports)
            else:
                self._operation(command, "clear", "Port_Group", port_group, "ports")
        for family in self._enabled_families():
            address_set = self.address_set_ids[family]
            addresses = tuple(
                json.dumps(endpoint[f"ipv{family}"]) for endpoint in desired
            )
            self._operation(command, "clear", "Address_Set", address_set, "addresses")
            if addresses:
                self._operation(
                    command,
                    "add",
                    "Address_Set",
                    address_set,
                    "addresses",
                    *addresses,
                )
        self.runner.run(*command)

    def set_endpoints(self, endpoints: Sequence[Mapping[str, object]]) -> None:
        self._require_created()
        normalized = self._normalize_endpoints(endpoints)
        if normalized == self.endpoints:
            return
        self._apply_endpoints(normalized)
        self.endpoints = normalized

    def add_endpoints(self, endpoints: Sequence[Mapping[str, object]]) -> None:
        self._require_created()
        additions = self._normalize_endpoints(endpoints)
        merged = {endpoint["port"]: endpoint for endpoint in self.endpoints}
        merged.update((endpoint["port"], endpoint) for endpoint in additions)
        desired = list(merged.values())
        if desired != self.endpoints:
            self._apply_endpoints(desired)
            self.endpoints = desired

    def remove_endpoints(self, endpoints: Sequence[Mapping[str, object]]) -> None:
        self._require_created()
        removals = self._normalize_endpoints(endpoints)
        ports = {endpoint["port"] for endpoint in removals}
        desired = [
            endpoint for endpoint in self.endpoints if endpoint["port"] not in ports
        ]
        if desired != self.endpoints:
            self._apply_endpoints(desired)
            self.endpoints = desired

    def enforce(self) -> None:
        self._require_created()
        if self.enforcing:
            return
        self._apply_endpoints(enforcing=True)
        self.enforcing = True

    def _ip_family(self, family: int) -> str:
        self._require_created()
        if isinstance(family, bool) or family not in (4, 6):
            raise ValueError("IP family must be 4 or 6")
        if not (self.ipv4 if family == 4 else self.ipv6):
            raise ValueError(f"IPv{family} is disabled for namespace {self.name}")
        return f"ip{family}"

    def _write_acl(self, acl: _Acl) -> None:
        target, direction, priority, match, action = acl
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

    def _delete_acl(self, acl: _Acl) -> None:
        self.runner.run(
            "ovn-nbctl",
            "--type=port-group",
            "acl-del",
            *acl[:-1],
        )

    def _set_acl(
        self,
        name: str,
        target: str,
        direction: str,
        priority: int,
        match: str,
        action: str,
    ) -> None:
        priority = _priority(priority)
        acl = (target, direction, priority, match, action)
        previous = self.acls.get(name)
        if previous == acl:
            return
        if previous is not None:
            self._delete_acl(previous)
        self._write_acl(acl)
        self.acls[name] = acl

    def _reset_acls(self) -> None:
        command: list[object] = ["ovn-nbctl"]
        for port_group in self.port_groups:
            self._operation(command, "clear", "Port_Group", port_group, "acls")
        self.runner.run(*command)

    def clear_policies(self) -> None:
        self._require_created()
        if not self.acls:
            return
        self._reset_acls()
        self.acls.clear()

    def default_deny(
        self,
        family: int,
        priority: int = 1,
        control_priority: int = 2,
    ) -> None:
        priority = _priority(priority)
        control_priority = _priority(control_priority)
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
        priority = _priority(priority)
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
        priority = _priority(priority)
        if self.runner is not other.runner:
            raise ValueError("namespaces must use the same runner")
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

    def _group(self, name: str) -> _NamespaceGroup:
        name = _text(name, "namespace group name")
        group = self.groups.get(name)
        if group is not None:
            return group
        suffix = hashlib.sha256(f"{self.name}\0{name}".encode()).hexdigest()[:16]
        group = _NamespaceGroup(
            port_group=f"sub_pg_{self.name}_{suffix}",
            address_sets={
                family: f"sub_as{'6' if family == 6 else ''}_{self.name}_{suffix}"
                for family in self._enabled_families()
            },
        )
        self.groups[name] = group
        return group

    def set_group(self, name: str, endpoints: Sequence[Mapping[str, object]]) -> None:
        self._require_created()
        normalized = self._normalize_endpoints(endpoints)
        ports = tuple(endpoint["port"] for endpoint in normalized)
        addresses = {
            family: tuple(endpoint[f"ipv{family}"] for endpoint in normalized)
            for family in self._enabled_families()
        }
        group = self._group(name)
        if group.ready and group.ports == ports and group.addresses == addresses:
            return
        if not group.ready:
            self.resources.ensure("Port_Group", group.port_group)
            for family, address_set in group.address_sets.items():
                group.address_set_ids[family] = self.resources.ensure(
                    "Address_Set", address_set
                )
            group.ready = True

        command: list[object] = ["ovn-nbctl"]
        if ports:
            self._operation(command, "pg-set-ports", group.port_group, *ports)
        else:
            self._operation(command, "clear", "Port_Group", group.port_group, "ports")
        for family, values in addresses.items():
            address_set = group.address_set_ids[family]
            self._operation(command, "clear", "Address_Set", address_set, "addresses")
            if values:
                self._operation(
                    command,
                    "add",
                    "Address_Set",
                    address_set,
                    "addresses",
                    *(json.dumps(value) for value in values),
                )
        self.runner.run(*command)
        group.ports = ports
        group.addresses = addresses

    def remove_group(self, name: str) -> None:
        self._require_created()
        group = self.groups.get(name)
        if group is None:
            return
        references = (
            f"@{group.port_group}",
            *(f"${address_set}" for address_set in group.address_sets.values()),
        )
        for acl_name, acl in tuple(self.acls.items()):
            if any(reference in acl[3] for reference in references):
                self._delete_acl(acl)
                del self.acls[acl_name]
        self.resources.delete("Port_Group", group.port_group)
        for address_set in group.address_sets.values():
            self.resources.delete("Address_Set", address_set)
        del self.groups[name]

    def allow_between(
        self,
        source: str,
        target: str,
        family: int,
        priority: int = 3,
    ) -> None:
        priority = _priority(priority)
        network = self._ip_family(family)
        try:
            source_group = self.groups[source]
            target_group = self.groups[target]
        except KeyError as error:
            raise ValueError(
                f"namespace group does not exist: {error.args[0]}"
            ) from error
        if not source_group.ready or not target_group.ready:
            raise ValueError("namespace group has not been configured")
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

    def allow_from_external(
        self,
        addresses: Sequence[str],
        family: int = 4,
        name: str = "external",
        priority: int = 3,
    ) -> None:
        priority = _priority(priority)
        network = self._ip_family(family)
        name = _text(name, "external policy name")
        values = (addresses,) if isinstance(addresses, str) else tuple(addresses)
        parsed = [ipaddress.ip_address(value) for value in values]
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

    def replace_load_balancer(
        self,
        name: str,
        protocol: str,
        vips: Mapping[str, Backends],
        group: Optional[str] = None,
        options: Mapping[str, str] = DEFAULT_OPTIONS,
    ) -> None:
        self._require_created()
        self.resources.load_balancers.replace(
            name,
            protocol,
            vips,
            group=group,
            options=options,
        )
        if name not in self.load_balancers:
            self.load_balancers.append(name)

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
            attempt(lambda name=name: self.resources.load_balancers.delete(name))
        for group in self.groups.values():
            attempt(
                lambda group=group: self.resources.delete(
                    "Port_Group", group.port_group
                )
            )
            for address_set in group.address_sets.values():
                attempt(
                    lambda address_set=address_set: self.resources.delete(
                        "Address_Set", address_set
                    )
                )
        for name in self.port_groups:
            attempt(lambda name=name: self.resources.delete("Port_Group", name))
        for family in self._enabled_families():
            name = self.address_sets[family]
            attempt(lambda name=name: self.resources.delete("Address_Set", name))
        self.cleaned = first_error is None
        self.created = not self.cleaned
        if first_error is not None:
            raise first_error

    def verify_cleanup(self) -> None:
        for name in self.load_balancers:
            if self.resources.load_balancers.contains(name):
                raise AssertionError(f"Load_Balancer remains after cleanup: {name}")
        for name in [
            *self.port_groups,
            *(group.port_group for group in self.groups.values()),
        ]:
            if self.resources.contains("Port_Group", name):
                raise AssertionError(f"Port_Group remains after cleanup: {name}")
        for name in [
            *(self.address_sets[family] for family in self._enabled_families()),
            *(
                name
                for group in self.groups.values()
                for name in group.address_sets.values()
            ),
        ]:
            if self.resources.contains("Address_Set", name):
                raise AssertionError(f"Address_Set remains after cleanup: {name}")
