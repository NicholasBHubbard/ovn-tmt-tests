import csv
import ipaddress
import json
import subprocess
from collections.abc import Iterable, Mapping, Sequence
from io import StringIO
from types import MappingProxyType
from typing import Optional, Union

from ovn_test.command import Runner

DEFAULT_OPTIONS: Mapping[str, str] = MappingProxyType(
    {
        "event": "false",
        "hairpin_snat_ip": "169.254.169.5 fd69::5",
        "neighbor_responder": "none",
        "reject": "true",
        "skip_snat": "false",
    }
)
VALID_PROTOCOLS = {"sctp", "tcp", "udp"}
Backends = Union[str, Sequence[str]]
Names = Union[str, Iterable[str]]


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} must be a non-empty string")
    return value


def _names(values: Names, label: str) -> tuple[str, ...]:
    items = (values,) if isinstance(values, str) else tuple(values)
    return tuple(dict.fromkeys(_text(item, label) for item in items))


def _references(runner: Runner, table: str, uuid: str) -> tuple[str, ...]:
    return tuple(
        runner.output(
            "ovn-nbctl",
            "--bare",
            "--columns=_uuid",
            "find",
            table,
            f"load_balancer{{>=}}{uuid}",
        ).split()
    )


def socket(address: str, port: int, family: int) -> str:
    if isinstance(family, bool) or not isinstance(family, int) or family not in (4, 6):
        raise ValueError("IP family must be 4 or 6")
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise ValueError("port must be an integer between 1 and 65535")
    try:
        parsed = ipaddress.ip_address(_text(address, "address"))
    except ValueError as error:
        raise ValueError(f"invalid IP address: {address}") from error
    if parsed.version != family:
        raise ValueError(f"{address} is not an IPv{family} address")
    return f"[{parsed}]:{port}" if family == 6 else f"{parsed}:{port}"


class LoadBalancers:
    def __init__(self, runner: Runner, owner: str) -> None:
        self.runner = runner
        self.owner = _text(owner, "owner")
        self._uuids: Optional[dict[str, str]] = None

    def _load(self) -> dict[str, str]:
        if self._uuids is not None:
            return self._uuids
        output = self.runner.output(
            "ovn-nbctl",
            "--format=csv",
            "--data=bare",
            "--no-headings",
            "--columns=_uuid,name",
            "find",
            "Load_Balancer",
            f"external_ids:ovn-tmt-tests-owner={json.dumps(self.owner)}",
        )
        self._uuids = {}
        for row in csv.reader(StringIO(output)):
            if len(row) != 2:
                raise RuntimeError("invalid load-balancer inventory returned by OVN")
            uuid, name = row
            if name in self._uuids:
                raise RuntimeError(f"load balancer {self.owner}/{name} is not unique")
            self._uuids[name] = uuid
        return self._uuids

    def replace(
        self,
        name: str,
        protocol: str,
        vips: Optional[Mapping[str, Backends]] = None,
        switches: Names = (),
        routers: Names = (),
        group: Optional[str] = None,
        options: Mapping[str, str] = DEFAULT_OPTIONS,
    ) -> subprocess.CompletedProcess[str]:
        name = _text(name, "load-balancer name")
        protocol = _text(protocol, "load-balancer protocol")
        if protocol not in VALID_PROTOCOLS:
            raise ValueError("load-balancer protocol must be tcp, udp or sctp")
        desired = (
            ("Logical_Switch", _names(switches, "switch name")),
            ("Logical_Router", _names(routers, "router name")),
            (
                "Load_Balancer_Group",
                () if group is None else (_text(group, "load-balancer group"),),
            ),
        )
        if not isinstance(options, Mapping):
            raise ValueError("load-balancer options must be a mapping")
        option_arguments = [
            f"options:{_text(key, 'option name')}="
            f"{json.dumps(_text(value, 'option value'))}"
            for key, value in options.items()
        ]
        if vips is not None and not isinstance(vips, Mapping):
            raise ValueError("load-balancer VIPs must be a mapping")
        vip_arguments = []
        for vip, raw_backends in (vips or {}).items():
            vip = _text(vip, "VIP")
            if isinstance(raw_backends, str):
                backends = raw_backends
            elif isinstance(raw_backends, Sequence):
                backends = ",".join(
                    _text(backend, "backend") for backend in raw_backends
                )
            else:
                raise ValueError("VIP backends must be a string or sequence of strings")
            vip_arguments.append(f"vips:{json.dumps(vip)}={json.dumps(backends)}")

        uuids = self._load()
        uuid = uuids.get(name)
        fields = [
            f"name={json.dumps(name)}",
            f"protocol={protocol}",
            f"external_ids:ovn-tmt-tests-owner={json.dumps(self.owner)}",
            *option_arguments,
            *vip_arguments,
        ]
        if uuid is None:
            reference = "@lb"
            command = [
                "ovn-nbctl",
                "--id=@lb",
                "create",
                "Load_Balancer",
                *fields,
            ]
        else:
            reference = uuid
            command = [
                "ovn-nbctl",
                "clear",
                "Load_Balancer",
                uuid,
                "vips",
                "options",
                "--",
                "set",
                "Load_Balancer",
                uuid,
                *fields,
            ]

        for table, objects in desired:
            if uuid is not None:
                for row in _references(self.runner, table, uuid):
                    command.extend(["--", "remove", table, row, "load_balancer", uuid])
            for item in objects:
                command.extend(["--", "add", table, item, "load_balancer", reference])
        result = self.runner.run(*command)
        if uuid is None:
            created = result.stdout.split()
            if len(created) != 1:
                raise RuntimeError("OVN did not return one load-balancer UUID")
            uuids[name] = created[0]
        return result

    def delete(self, name: str) -> None:
        name = _text(name, "load-balancer name")
        uuids = self._load()
        uuid = uuids.get(name)
        if uuid is not None:
            self.runner.run("ovn-nbctl", "destroy", "Load_Balancer", uuid)
            del uuids[name]
