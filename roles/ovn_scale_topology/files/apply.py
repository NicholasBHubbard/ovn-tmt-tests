import json
import os
import subprocess
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import cast

OWNER = "ovn-tmt-tests-owner"
IDENTIFIER = "ovn-tmt-tests-id"
SCOPE = "ovn-tmt-tests-scope"
Command = list[object]
CommandGroup = list[Command]
RowsByKind = Mapping[str, list[dict[str, object]]]


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


def _run(*args: object) -> str:
    return subprocess.run(
        ["ovn-nbctl", *map(str, args)],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    ).stdout.strip()


def _rows(table: str, *columns: str) -> list[dict[str, object]]:
    result = json.loads(
        _run(
            "--format=json",
            "--data=json",
            f"--columns={','.join(columns)}",
            "find",
            table,
        )
    )
    return [
        {
            heading: _decode(value)
            for heading, value in zip(result["headings"], row, strict=True)
        }
        for row in result["data"]
    ]


def _references(rows: Sequence[dict[str, object]], column: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for row in rows:
        values = row[column]
        values = values if isinstance(values, list) else [values]
        name = _text(row, "name")
        result.update({str(value): name for value in values if value})
    return result


def _batch(groups: Sequence[CommandGroup], size: int = 50) -> None:
    for offset in range(0, len(groups), size):
        arguments = []
        for group in groups[offset : offset + size]:
            for command in group:
                if arguments:
                    arguments.append("--")
                arguments.extend(command)
        if arguments:
            _run(*arguments)


def _quoted(value: object) -> str:
    return json.dumps(value, separators=(",", ":"))


def _external_id(key: str, value: object) -> str:
    return f"external_ids:{key}={_quoted(value)}"


def _items(data: Mapping[str, object], key: str) -> list[dict[str, object]]:
    value = data[key]
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise TypeError(f"{key} is not a list of mappings")
    return cast(list[dict[str, object]], value)


def _mapping(data: Mapping[str, object], key: str) -> dict[str, object]:
    value = data.get(key, {})
    if not isinstance(value, dict):
        raise TypeError(f"{key} is not a mapping")
    return cast(dict[str, object], value)


def _text(data: Mapping[str, object], key: str) -> str:
    value = data[key]
    if not isinstance(value, str):
        raise TypeError(f"{key} is not text")
    return value


def _strings(data: Mapping[str, object], key: str) -> list[str]:
    value = data.get(key, [])
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise TypeError(f"{key} is not a list of text")
    return cast(list[str], value)


def _options(
    table: str, name: str, column: str, values: Mapping[str, object]
) -> CommandGroup:
    commands: CommandGroup = [["clear", table, name, column]]
    commands.extend(
        ["set", table, name, f"{column}:{key}={_quoted(str(value).lower())}"]
        for key, value in values.items()
    )
    return commands


def _managed(rows: Sequence[dict[str, object]], owner: str) -> list[dict[str, object]]:
    return [row for row in rows if _mapping(row, "external_ids").get(OWNER) == owner]


def _identified(rows: Sequence[dict[str, object]]) -> dict[str, dict[str, object]]:
    return {
        _text(_mapping(row, "external_ids"), IDENTIFIER): row
        for row in rows
        if _mapping(row, "external_ids").get(IDENTIFIER)
    }


def _configure_roots(topology: dict[str, object], owner: str) -> None:
    groups: list[CommandGroup] = []
    for switch in _items(topology, "switches"):
        name = _text(switch, "name")
        groups.append(
            [
                ["--may-exist", "ls-add", name],
                ["set", "Logical_Switch", name, _external_id(OWNER, owner)],
                *_options(
                    "Logical_Switch",
                    name,
                    "other_config",
                    _mapping(switch, "other_config"),
                ),
            ]
        )
    for router in _items(topology, "routers"):
        name = _text(router, "name")
        groups.append(
            [
                ["--may-exist", "lr-add", name],
                ["set", "Logical_Router", name, _external_id(OWNER, owner)],
                *_options(
                    "Logical_Router",
                    name,
                    "options",
                    _mapping(router, "options"),
                ),
            ]
        )
    _batch(groups)


def _configure_ports(
    topology: dict[str, object],
    owner: str,
    routers: Sequence[dict[str, object]],
    switches: Sequence[dict[str, object]],
    router_ports: Sequence[dict[str, object]],
    switch_ports: Sequence[dict[str, object]],
) -> None:
    router_parent = _references(routers, "ports")
    switch_parent = _references(switches, "ports")
    router_ports_by_name = {_text(row, "name"): row for row in router_ports}
    switch_ports_by_name = {_text(row, "name"): row for row in switch_ports}
    groups: list[CommandGroup] = []

    for port in _items(topology, "router_ports"):
        name = _text(port, "name")
        switch_name = _text(port, "switch_port")
        commands: CommandGroup = []
        current = router_ports_by_name.get(name)
        if current:
            old_parent = router_parent.get(_text(current, "_uuid"))
            if old_parent != port["router"]:
                commands.extend(
                    [
                        [
                            "remove",
                            "Logical_Router",
                            old_parent,
                            "ports",
                            current["_uuid"],
                        ],
                        [
                            "add",
                            "Logical_Router",
                            port["router"],
                            "ports",
                            current["_uuid"],
                        ],
                    ]
                )
        else:
            commands.append(
                [
                    "lrp-add",
                    port["router"],
                    name,
                    port["mac"],
                    *_strings(port, "networks"),
                ]
            )
        commands.extend(
            [
                [
                    "set",
                    "Logical_Router_Port",
                    name,
                    f"mac={_quoted(port['mac'])}",
                    f"networks={_quoted(port.get('networks', []))}",
                    _external_id(OWNER, owner),
                ],
                *_options(
                    "Logical_Router_Port",
                    name,
                    "options",
                    _mapping(port, "options"),
                ),
            ]
        )

        current = switch_ports_by_name.get(switch_name)
        if current:
            old_parent = switch_parent.get(_text(current, "_uuid"))
            if old_parent != port["switch"]:
                commands.extend(
                    [
                        [
                            "remove",
                            "Logical_Switch",
                            old_parent,
                            "ports",
                            current["_uuid"],
                        ],
                        [
                            "add",
                            "Logical_Switch",
                            port["switch"],
                            "ports",
                            current["_uuid"],
                        ],
                    ]
                )
        else:
            commands.append(["lsp-add", port["switch"], switch_name])
        commands.extend(
            [
                ["lsp-set-type", switch_name, "router"],
                ["lsp-set-addresses", switch_name, "router"],
                ["lsp-set-options", switch_name, f"router-port={name}"],
                [
                    "set",
                    "Logical_Switch_Port",
                    switch_name,
                    _external_id(OWNER, owner),
                ],
            ]
        )
        groups.append(commands)

    for port in _items(topology, "localnet_ports"):
        name = _text(port, "name")
        commands: CommandGroup = []
        current = switch_ports_by_name.get(name)
        if current:
            old_parent = switch_parent.get(_text(current, "_uuid"))
            if old_parent != port["switch"]:
                commands.extend(
                    [
                        [
                            "remove",
                            "Logical_Switch",
                            old_parent,
                            "ports",
                            current["_uuid"],
                        ],
                        [
                            "add",
                            "Logical_Switch",
                            port["switch"],
                            "ports",
                            current["_uuid"],
                        ],
                    ]
                )
        else:
            commands.append(
                ["lsp-add-localnet-port", port["switch"], name, port["network"]]
            )
        commands.extend(
            [
                ["lsp-set-type", name, "localnet"],
                ["lsp-set-addresses", name, "unknown"],
                ["lsp-set-options", name, f"network_name={port['network']}"],
                [
                    "set",
                    "Logical_Switch_Port",
                    name,
                    f"tag_request={_quoted(port.get('tag', []))}",
                    _external_id(OWNER, owner),
                ],
                ["clear", "Logical_Switch_Port", name, "tag"],
            ]
        )
        groups.append(commands)

    _batch(groups)


def _configure_gateway_chassis(
    topology: dict[str, object],
    router_ports: Sequence[dict[str, object]],
    gateway_chassis: Sequence[dict[str, object]],
) -> None:
    parent = _references(router_ports, "gateway_chassis")
    current = {_text(row, "name"): row for row in gateway_chassis}
    groups: list[CommandGroup] = []
    for index, assignment in enumerate(_items(topology, "gateway_chassis")):
        name = _text(assignment, "id")
        row = current.get(name)
        commands: CommandGroup = []
        if row:
            old_parent = parent.get(_text(row, "_uuid"))
            if old_parent != assignment["router_port"]:
                commands.extend(
                    [
                        [
                            "remove",
                            "Logical_Router_Port",
                            old_parent,
                            "gateway_chassis",
                            row["_uuid"],
                        ],
                        [
                            "add",
                            "Logical_Router_Port",
                            assignment["router_port"],
                            "gateway_chassis",
                            row["_uuid"],
                        ],
                    ]
                )
            target = row["_uuid"]
        else:
            target = f"@gateway{index}"
            commands.extend(
                [
                    [
                        f"--id={target}",
                        "create",
                        "Gateway_Chassis",
                        f"name={_quoted(name)}",
                        f"chassis_name={_quoted(assignment['chassis'])}",
                        f"priority={assignment.get('priority', 0)}",
                    ],
                    [
                        "add",
                        "Logical_Router_Port",
                        assignment["router_port"],
                        "gateway_chassis",
                        target,
                    ],
                ]
            )
        if row:
            commands.append(
                [
                    "set",
                    "Gateway_Chassis",
                    target,
                    f"name={_quoted(name)}",
                    f"chassis_name={_quoted(assignment['chassis'])}",
                    f"priority={assignment.get('priority', 0)}",
                ]
            )
        groups.append(commands)
    _batch(groups)


def _configure_routes(
    topology: dict[str, object],
    routers: Sequence[dict[str, object]],
    routes: Sequence[dict[str, object]],
    owner: str,
) -> None:
    parent = _references(routers, "static_routes")
    current = _identified(routes)
    groups: list[CommandGroup] = []
    for index, route in enumerate(_items(topology, "static_routes")):
        row = current.get(_text(route, "id"))
        commands: CommandGroup = []
        if row:
            old_parent = parent.get(_text(row, "_uuid"))
            if old_parent != route["router"]:
                commands.extend(
                    [
                        [
                            "remove",
                            "Logical_Router",
                            old_parent,
                            "static_routes",
                            row["_uuid"],
                        ],
                        [
                            "add",
                            "Logical_Router",
                            route["router"],
                            "static_routes",
                            row["_uuid"],
                        ],
                    ]
                )
            target = row["_uuid"]
        else:
            target = f"@route{index}"
            commands.extend(
                [
                    [
                        f"--id={target}",
                        "create",
                        "Logical_Router_Static_Route",
                        f"ip_prefix={_quoted(route['prefix'])}",
                        f"nexthop={_quoted(route['nexthop'])}",
                        f"policy={_quoted(route.get('policy', 'dst-ip'))}",
                        f"route_table={_quoted(route.get('route_table', ''))}",
                        f"output_port={_quoted(route.get('output_port', []))}",
                        _external_id(IDENTIFIER, route["id"]),
                        _external_id(SCOPE, owner),
                    ],
                    [
                        "add",
                        "Logical_Router",
                        route["router"],
                        "static_routes",
                        target,
                    ],
                ]
            )
        if row:
            commands.append(
                [
                    "set",
                    "Logical_Router_Static_Route",
                    target,
                    f"ip_prefix={_quoted(route['prefix'])}",
                    f"nexthop={_quoted(route['nexthop'])}",
                    f"policy={_quoted(route.get('policy', 'dst-ip'))}",
                    f"route_table={_quoted(route.get('route_table', ''))}",
                    f"output_port={_quoted(route.get('output_port', []))}",
                    _external_id(IDENTIFIER, route["id"]),
                    _external_id(SCOPE, owner),
                ]
            )
        groups.append(commands)
    _batch(groups)


def _configure_nat(
    topology: dict[str, object],
    routers: Sequence[dict[str, object]],
    rules: Sequence[dict[str, object]],
    owner: str,
) -> None:
    parent = _references(routers, "nat")
    current = _identified(rules)
    groups: list[CommandGroup] = []
    for index, rule in enumerate(_items(topology, "nat_rules")):
        row = current.get(_text(rule, "id"))
        commands: CommandGroup = []
        if row:
            old_parent = parent.get(_text(row, "_uuid"))
            if old_parent != rule["router"]:
                commands.extend(
                    [
                        ["remove", "Logical_Router", old_parent, "nat", row["_uuid"]],
                        ["add", "Logical_Router", rule["router"], "nat", row["_uuid"]],
                    ]
                )
            target = row["_uuid"]
        else:
            target = f"@nat{index}"
            commands.extend(
                [
                    [
                        f"--id={target}",
                        "create",
                        "NAT",
                        f"type={_quoted(rule['type'])}",
                        f"external_ip={_quoted(rule['external_ip'])}",
                        f"logical_ip={_quoted(rule['logical_ip'])}",
                        _external_id(IDENTIFIER, rule["id"]),
                        _external_id(OWNER, owner),
                    ],
                    ["add", "Logical_Router", rule["router"], "nat", target],
                ]
            )
        if row:
            commands.append(
                [
                    "set",
                    "NAT",
                    target,
                    f"type={_quoted(rule['type'])}",
                    f"external_ip={_quoted(rule['external_ip'])}",
                    f"logical_ip={_quoted(rule['logical_ip'])}",
                    _external_id(IDENTIFIER, rule["id"]),
                    _external_id(OWNER, owner),
                ]
            )
        groups.append(commands)
    _batch(groups)


def _cleanup(topology: dict[str, object], owner: str, state: RowsByKind) -> None:
    desired = _mapping(topology, "managed")
    desired_switch_ports = {
        _text(port, "switch_port") for port in _items(topology, "router_ports")
    } | {_text(port, "name") for port in _items(topology, "localnet_ports")}
    desired_routes = {_text(route, "id") for route in _items(topology, "static_routes")}
    desired_nat = {_text(rule, "id") for rule in _items(topology, "nat_rules")}
    desired_gateway = {
        _text(item, "id") for item in _items(topology, "gateway_chassis")
    }
    groups: list[CommandGroup] = []

    gateway_parent = _references(state["router_ports"], "gateway_chassis")
    for row in state["gateway_chassis"]:
        name = _text(row, "name")
        if name.startswith(f"{owner}:") and name not in desired_gateway:
            groups.append(
                [
                    [
                        "remove",
                        "Logical_Router_Port",
                        gateway_parent[_text(row, "_uuid")],
                        "gateway_chassis",
                        row["_uuid"],
                    ]
                ]
            )

    for row in _managed(state["switch_ports"], owner):
        name = _text(row, "name")
        if name not in desired_switch_ports:
            groups.append([["--if-exists", "lsp-del", name]])
    for row in _managed(state["router_ports"], owner):
        name = _text(row, "name")
        if name not in _strings(desired, "router_ports"):
            groups.append([["--if-exists", "lrp-del", name]])

    router_route_parent = _references(state["routers"], "static_routes")
    for row in state["routes"]:
        external_ids = _mapping(row, "external_ids")
        if (
            external_ids.get(SCOPE) == owner
            and external_ids.get(IDENTIFIER) not in desired_routes
        ):
            groups.append(
                [
                    [
                        "remove",
                        "Logical_Router",
                        router_route_parent[_text(row, "_uuid")],
                        "static_routes",
                        row["_uuid"],
                    ]
                ]
            )

    router_nat_parent = _references(state["routers"], "nat")
    for row in _managed(state["nat"], owner):
        if _mapping(row, "external_ids").get(IDENTIFIER) not in desired_nat:
            groups.append(
                [
                    [
                        "remove",
                        "Logical_Router",
                        router_nat_parent[_text(row, "_uuid")],
                        "nat",
                        row["_uuid"],
                    ]
                ]
            )

    for row in _managed(state["switches"], owner):
        name = _text(row, "name")
        if name not in _strings(desired, "switches"):
            groups.append([["--if-exists", "ls-del", name]])
    for row in _managed(state["routers"], owner):
        name = _text(row, "name")
        if name not in _strings(desired, "routers"):
            groups.append([["--if-exists", "lr-del", name]])
    _batch(groups)


def _record_removed(topology: dict[str, object], state: RowsByKind) -> None:
    expected = _mapping(topology, "southbound")
    owner = _text(topology, "owner")
    previous_datapaths = {
        _text(row, "name")
        for table in ("switches", "routers")
        for row in _managed(state[table], owner)
    }
    previous_ports = {
        _text(row, "name") for row in _managed(state["switch_ports"], owner)
    }
    expected["absent_datapaths"] = sorted(
        previous_datapaths - set(_strings(expected, "datapaths"))
    )
    expected["absent_ports"] = sorted(previous_ports - set(_strings(expected, "ports")))


def apply(topology: dict[str, object]) -> None:
    owner = _text(topology, "owner")
    _mapping(topology, "southbound")["started_ns"] = time.monotonic_ns()
    _configure_roots(topology, owner)

    switches = _rows("Logical_Switch", "_uuid", "name", "external_ids", "ports")
    routers = _rows(
        "Logical_Router",
        "_uuid",
        "name",
        "external_ids",
        "ports",
        "static_routes",
        "nat",
    )
    router_ports = _rows(
        "Logical_Router_Port",
        "_uuid",
        "name",
        "external_ids",
        "gateway_chassis",
    )
    switch_ports = _rows("Logical_Switch_Port", "_uuid", "name", "external_ids")
    routes = _rows("Logical_Router_Static_Route", "_uuid", "external_ids")
    nat = _rows("NAT", "_uuid", "external_ids")
    gateway_chassis = _rows("Gateway_Chassis", "_uuid", "name")

    _configure_ports(
        topology,
        owner,
        routers,
        switches,
        router_ports,
        switch_ports,
    )
    _configure_gateway_chassis(topology, router_ports, gateway_chassis)
    _configure_routes(topology, routers, routes, owner)
    _configure_nat(topology, routers, nat, owner)
    state: dict[str, list[dict[str, object]]] = {
        "switches": switches,
        "routers": routers,
        "router_ports": router_ports,
        "switch_ports": switch_ports,
        "routes": routes,
        "nat": nat,
        "gateway_chassis": gateway_chassis,
    }
    _record_removed(topology, state)
    _cleanup(
        topology,
        owner,
        state,
    )

    print(
        json.dumps(
            {
                "workers": len(_items(topology, "workers")),
                "switches": len(_items(topology, "switches")),
                "routers": len(_items(topology, "routers")),
            }
        )
    )


def main() -> None:
    path = Path(os.environ["OVN_SCALE_TOPOLOGY_PATH"])
    topology = json.loads(path.read_text())
    apply(topology)
    path.write_text(json.dumps(topology))


if __name__ == "__main__":
    main()
