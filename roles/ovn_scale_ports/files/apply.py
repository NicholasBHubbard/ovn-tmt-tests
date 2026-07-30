import json
import os
import subprocess
import time
from collections.abc import Sequence
from pathlib import Path
from typing import TypedDict, cast

OWNER = "ovn-tmt-tests-owner"
Command = list[object]
CommandGroup = list[Command]


class Port(TypedDict):
    name: str
    interface: str
    switch: str
    bridge: str
    addresses: str
    mtu: int


class Southbound(TypedDict):
    datapaths: list[str]
    ports: list[str]
    absent_datapaths: list[str]
    absent_ports: list[str]
    started_ns: int


class State(TypedDict):
    owner: str
    nbctl: list[str]
    ovs_vsctl: list[str]
    ports: list[Port]
    southbound: Southbound


def _decode(value: object) -> object:
    if not isinstance(value, list) or len(value) != 2:
        return value
    kind, contents = value
    if not isinstance(kind, str):
        return value
    if kind in {"uuid", "named-uuid"}:
        return contents
    if kind == "set" and isinstance(contents, list):
        return [_decode(item) for item in contents]
    if kind == "map" and isinstance(contents, list):
        result = {}
        for pair in contents:
            if not isinstance(pair, list) or len(pair) != 2:
                return value
            key, item = pair
            result[_decode(key)] = _decode(item)
        return result
    return value


def _run(command: Sequence[object]) -> str:
    return subprocess.run(
        list(map(str, command)),
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    ).stdout.strip()


def _rows(command: Sequence[str], table: str, *columns: str) -> list[dict[str, object]]:
    result = json.loads(
        _run(
            [
                *command,
                "--format=json",
                "--data=json",
                f"--columns={','.join(columns)}",
                "find",
                table,
            ]
        )
    )
    return [
        {
            heading: _decode(value)
            for heading, value in zip(result["headings"], row, strict=True)
        }
        for row in result["data"]
    ]


def _batch(
    command: Sequence[str], groups: Sequence[CommandGroup], size: int = 50
) -> None:
    for offset in range(0, len(groups), size):
        arguments = []
        for group in groups[offset : offset + size]:
            for item in group:
                if arguments:
                    arguments.append("--")
                arguments.extend(item)
        if arguments:
            _run([*command, *arguments])


def _quoted(value: object) -> str:
    return json.dumps(value, separators=(",", ":"))


def _external_id(key: str, value: object) -> str:
    return f"external_ids:{key}={_quoted(value)}"


def _references(rows: Sequence[dict[str, object]], column: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for row in rows:
        values = row[column]
        values = values if isinstance(values, list) else [values]
        name = row["name"]
        if not isinstance(name, str):
            raise TypeError("OVSDB name is not text")
        result.update({str(value): name for value in values if value})
    return result


def _external_ids(row: dict[str, object]) -> dict[str, object]:
    value = row.get("external_ids", {})
    if not isinstance(value, dict):
        return {}
    return {str(key): item for key, item in value.items()}


def _text(row: dict[str, object], column: str) -> str:
    value = row[column]
    if not isinstance(value, str):
        raise TypeError(f"OVSDB {column} is not text")
    return value


def _configure_nb(state: State) -> None:
    command = state["nbctl"]
    owner = state["owner"]
    switches = _rows(command, "Logical_Switch", "_uuid", "name", "ports")
    rows = _rows(command, "Logical_Switch_Port", "_uuid", "name", "external_ids")
    parents = _references(switches, "ports")
    current = {str(row["name"]): row for row in rows}
    wanted = {port["name"] for port in state["ports"]}
    groups: list[CommandGroup] = []

    for port in state["ports"]:
        name = port["name"]
        row = current.get(name)
        commands: CommandGroup = []
        if row:
            parent = parents.get(_text(row, "_uuid"))
            if parent != port["switch"]:
                commands.extend(
                    [
                        ["remove", "Logical_Switch", parent, "ports", row["_uuid"]],
                        [
                            "add",
                            "Logical_Switch",
                            port["switch"],
                            "ports",
                            row["_uuid"],
                        ],
                    ]
                )
        else:
            commands.append(["lsp-add", port["switch"], name])
        commands.extend(
            [
                ["lsp-set-type", name, ""],
                ["lsp-set-options", name],
                ["lsp-set-addresses", name, port["addresses"]],
                ["lsp-set-port-security", name, port["addresses"]],
                ["set", "Logical_Switch_Port", name, _external_id(OWNER, owner)],
            ]
        )
        groups.append(commands)

    stale = [
        _text(row, "name")
        for row in rows
        if _external_ids(row).get(OWNER) == owner and row["name"] not in wanted
    ]
    groups.extend([[["--if-exists", "lsp-del", name]] for name in stale])
    state["southbound"]["absent_ports"] = sorted(stale)
    _batch(command, groups)


def _configure_ovs(state: State) -> None:
    owner = state["owner"]
    command = state["ovs_vsctl"]
    bridges = _rows(command, "Bridge", "_uuid", "name", "ports")
    rows = _rows(command, "Port", "_uuid", "name", "external_ids")
    parents = _references(bridges, "ports")
    current = {str(row["name"]): row for row in rows}
    wanted = {port["interface"] for port in state["ports"]}
    groups: list[CommandGroup] = []

    for port in state["ports"]:
        interface = port["interface"]
        row = current.get(interface)
        commands: CommandGroup = []
        if row:
            parent = parents.get(_text(row, "_uuid"))
            if parent != port["bridge"]:
                commands.extend(
                    [
                        ["remove", "Bridge", parent, "ports", row["_uuid"]],
                        ["add", "Bridge", port["bridge"], "ports", row["_uuid"]],
                    ]
                )
        else:
            commands.append(["--may-exist", "add-port", port["bridge"], interface])
        commands.extend(
            [
                ["set", "Port", interface, _external_id(OWNER, owner)],
                [
                    "set",
                    "Interface",
                    interface,
                    "type=internal",
                    _external_id("iface-id", port["name"]),
                    _external_id(OWNER, owner),
                ],
                (
                    ["set", "Interface", interface, f"mtu_request={port['mtu']}"]
                    if port["mtu"]
                    else ["clear", "Interface", interface, "mtu_request"]
                ),
            ]
        )
        groups.append(commands)

    groups.extend(
        [["--if-exists", "del-port", row["name"]]]
        for row in rows
        if _external_ids(row).get(OWNER) == owner and row["name"] not in wanted
    )
    _batch(command, groups)


def apply(state: State) -> None:
    state["southbound"]["started_ns"] = time.monotonic_ns()
    _configure_nb(state)
    _configure_ovs(state)


def main() -> None:
    path = Path(os.environ["OVN_SCALE_PORTS_PATH"])
    state = json.loads(path.read_text())
    apply(cast(State, state))
    path.write_text(json.dumps(state))


if __name__ == "__main__":
    main()
