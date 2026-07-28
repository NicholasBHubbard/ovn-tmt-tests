import json
import os
import subprocess
import time
from pathlib import Path


OWNER = "ovn-tmt-tests-owner"


def _decode(value):
    if not isinstance(value, list) or len(value) != 2:
        return value
    kind, contents = value
    if kind in {"uuid", "named-uuid"}:
        return contents
    if kind == "set":
        return [_decode(item) for item in contents]
    if kind == "map":
        return {_decode(key): _decode(item) for key, item in contents}
    return value


def _run(command):
    return subprocess.run(
        list(map(str, command)),
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    ).stdout.strip()


def _rows(command, table, *columns):
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


def _batch(command, groups, size=50):
    for offset in range(0, len(groups), size):
        arguments = []
        for group in groups[offset : offset + size]:
            for item in group:
                if arguments:
                    arguments.append("--")
                arguments.extend(item)
        if arguments:
            _run([*command, *arguments])


def _quoted(value):
    return json.dumps(value, separators=(",", ":"))


def _external_id(key, value):
    return f"external_ids:{key}={_quoted(value)}"


def _references(rows, column):
    result = {}
    for row in rows:
        values = row[column]
        values = values if isinstance(values, list) else [values]
        result.update({value: row["name"] for value in values if value})
    return result


def _configure_nb(state):
    command = state["nbctl"]
    owner = state["owner"]
    switches = _rows(command, "Logical_Switch", "_uuid", "name", "ports")
    rows = _rows(command, "Logical_Switch_Port", "_uuid", "name", "external_ids")
    parents = _references(switches, "ports")
    current = {row["name"]: row for row in rows}
    wanted = {port["name"] for port in state["ports"]}
    groups = []

    for port in state["ports"]:
        name = port["name"]
        row = current.get(name)
        commands = []
        if row:
            parent = parents.get(row["_uuid"])
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
        row["name"]
        for row in rows
        if row.get("external_ids", {}).get(OWNER) == owner and row["name"] not in wanted
    ]
    groups.extend([[["--if-exists", "lsp-del", name]] for name in stale])
    state["southbound"]["absent_ports"] = sorted(stale)
    _batch(command, groups)


def _configure_ovs(state):
    owner = state["owner"]
    command = state["ovs_vsctl"]
    bridges = _rows(command, "Bridge", "_uuid", "name", "ports")
    rows = _rows(command, "Port", "_uuid", "name", "external_ids")
    parents = _references(bridges, "ports")
    current = {row["name"]: row for row in rows}
    wanted = {port["interface"] for port in state["ports"]}
    groups = []

    for port in state["ports"]:
        interface = port["interface"]
        row = current.get(interface)
        commands = []
        if row:
            parent = parents.get(row["_uuid"])
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
        if row.get("external_ids", {}).get(OWNER) == owner and row["name"] not in wanted
    )
    _batch(command, groups)


def apply(state):
    state["southbound"]["started_ns"] = time.monotonic_ns()
    _configure_nb(state)
    _configure_ovs(state)


def main():
    path = Path(os.environ["OVN_SCALE_PORTS_PATH"])
    state = json.loads(path.read_text())
    apply(state)
    path.write_text(json.dumps(state))


if __name__ == "__main__":
    main()
