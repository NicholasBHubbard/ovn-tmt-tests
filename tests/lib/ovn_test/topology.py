import os
from collections.abc import Mapping
from copy import deepcopy
from pathlib import Path
from typing import Any, Optional, Union

import yaml


def _ordered_names(
    value: object, available: Mapping[object, object], label: str
) -> tuple[str, ...]:
    if (
        not isinstance(value, list)
        or any(not isinstance(name, str) or not name for name in value)
        or len(value) != len(set(value))
        or set(value) != set(available)
    ):
        raise ValueError(
            f"invalid tmt topology: {label} must list each corresponding name once"
        )
    return tuple(name for name in value if isinstance(name, str))


class Topology:
    def __init__(self, data: Mapping[str, Any]) -> None:
        if not isinstance(data, Mapping):
            raise ValueError("invalid tmt topology: expected a mapping")
        guest = data.get("guest")
        guests = data.get("guests")
        roles = data.get("roles")
        if not isinstance(guest, dict) or not isinstance(guests, dict):
            raise ValueError("invalid tmt topology: guest data must be mappings")
        if not isinstance(roles, dict):
            raise ValueError("invalid tmt topology: roles must be a mapping")
        if any(not isinstance(name, str) or not name for name in guests):
            raise ValueError(
                "invalid tmt topology: guest names must be non-empty strings"
            )
        if any(not isinstance(name, str) or not name for name in roles):
            raise ValueError(
                "invalid tmt topology: role names must be non-empty strings"
            )

        guest_names = _ordered_names(data.get("guest-names"), guests, "guest-names")
        role_names = _ordered_names(data.get("role-names"), roles, "role-names")
        hostnames = {}
        guest_roles = {}
        for name, information in guests.items():
            if not isinstance(information, dict) or information.get("name") != name:
                raise ValueError(
                    "invalid tmt topology: guest entries must match their names"
                )
            hostname = information.get("hostname")
            role = information.get("role")
            if hostname is not None and (not isinstance(hostname, str) or not hostname):
                raise ValueError(
                    "invalid tmt topology: guest hostnames must be strings or null"
                )
            if role is not None and (not isinstance(role, str) or not role):
                raise ValueError(
                    "invalid tmt topology: guest roles must be strings or null"
                )
            hostnames[name] = hostname
            guest_roles[name] = role

        normalized_roles = {}
        for role, members in roles.items():
            if (
                not isinstance(members, list)
                or not members
                or any(not isinstance(member, str) for member in members)
                or len(members) != len(set(members))
            ):
                raise ValueError(
                    "invalid tmt topology: role members must be unique guest names"
                )
            if any(
                member not in hostnames or guest_roles[member] != role
                for member in members
            ):
                raise ValueError(
                    "invalid tmt topology: role membership is inconsistent"
                )
            normalized_roles[role] = tuple(members)
        if any(
            role is not None
            and (role not in normalized_roles or name not in normalized_roles[role])
            for name, role in guest_roles.items()
        ):
            raise ValueError(
                "invalid tmt topology: guest role membership is inconsistent"
            )

        current = guest.get("name")
        if (
            not isinstance(current, str)
            or current not in guests
            or any(
                guest.get(field) != guests[current].get(field)
                for field in ("name", "hostname", "role")
            )
        ):
            raise ValueError("invalid tmt topology: current guest is inconsistent")

        self._data: dict[str, Any] = deepcopy(dict(data))
        self._current = current
        self._guest_names = guest_names
        self._role_names = role_names
        self._hostnames = hostnames
        self._roles = normalized_roles

    @property
    def current(self) -> str:
        return self._current

    def to_dict(self) -> dict[str, Any]:
        return deepcopy(self._data)

    @classmethod
    def from_file(cls, path: Union[str, os.PathLike[str]]) -> "Topology":
        path = Path(path)
        try:
            with path.open(encoding="utf-8") as source:
                data = yaml.safe_load(source)
        except yaml.YAMLError as error:
            raise ValueError(f"invalid tmt topology YAML: {path}") from error
        return cls(data)

    @classmethod
    def from_environment(
        cls, environment: Optional[Mapping[str, str]] = None
    ) -> "Topology":
        environment = os.environ if environment is None else environment
        path = environment.get("TMT_TOPOLOGY_YAML")
        if not path:
            raise ValueError("TMT_TOPOLOGY_YAML must be set")
        return cls.from_file(path)

    def role(self, name: str) -> list[str]:
        try:
            return list(self._roles[name])
        except KeyError:
            raise KeyError(f"unknown topology role: {name}") from None

    def roles(self) -> list[str]:
        return list(self._role_names)

    def guests(self) -> list[str]:
        return list(self._guest_names)

    def hostname(self, guest: str) -> str:
        try:
            hostname = self._hostnames[guest]
        except KeyError:
            raise KeyError(f"unknown topology guest: {guest}") from None
        if hostname is None:
            raise ValueError(f"topology guest has no hostname: {guest}")
        return hostname

    def is_local(self, guest: str) -> bool:
        if guest not in self._hostnames:
            raise KeyError(f"unknown topology guest: {guest}")
        return guest == self.current
