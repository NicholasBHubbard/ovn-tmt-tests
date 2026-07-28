import json
import os
import subprocess
import time
from pathlib import Path


OWNER = "ovn-tmt-tests-owner"
IDENTIFIER = "ovn-tmt-tests-id"
SCOPE = "ovn-tmt-tests-scope"


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


def _run(*args):
    return subprocess.run(
        ["ovn-nbctl", *map(str, args)],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    ).stdout.strip()


def _rows(table, *columns):
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


def _references(rows, column):
    result = {}
    for row in rows:
        values = row[column]
        values = values if isinstance(values, list) else [values]
        result.update({value: row["name"] for value in values if value})
    return result


def _batch(groups, size=50):
    for offset in range(0, len(groups), size):
        arguments = []
        for command in sum(groups[offset : offset + size], []):
            if arguments:
                arguments.append("--")
            arguments.extend(command)
        if arguments:
            _run(*arguments)


def _quoted(value):
    return json.dumps(value, separators=(",", ":"))


def _external_id(key, value):
    return f"external_ids:{key}={_quoted(value)}"


def _options(table, name, column, values):
    commands = [["clear", table, name, column]]
    commands.extend(
        ["set", table, name, f"{column}:{key}={_quoted(str(value).lower())}"]
        for key, value in values.items()
    )
    return commands


def _managed(rows, owner):
    return [row for row in rows if row.get("external_ids", {}).get(OWNER) == owner]


def _identified(rows):
    return {
        row.get("external_ids", {}).get(IDENTIFIER): row
        for row in rows
        if row.get("external_ids", {}).get(IDENTIFIER)
    }


def _configure_roots(topology, owner):
    groups = []
    for switch in topology["switches"]:
        name = switch["name"]
        groups.append(
            [
                ["--may-exist", "ls-add", name],
                ["set", "Logical_Switch", name, _external_id(OWNER, owner)],
                *_options(
                    "Logical_Switch",
                    name,
                    "other_config",
                    switch.get("other_config", {}),
                ),
            ]
        )
    for router in topology["routers"]:
        name = router["name"]
        groups.append(
            [
                ["--may-exist", "lr-add", name],
                ["set", "Logical_Router", name, _external_id(OWNER, owner)],
                *_options(
                    "Logical_Router",
                    name,
                    "options",
                    router.get("options", {}),
                ),
            ]
        )
    _batch(groups)


def _configure_ports(topology, owner, routers, switches, router_ports, switch_ports):
    router_parent = _references(routers, "ports")
    switch_parent = _references(switches, "ports")
    router_ports = {row["name"]: row for row in router_ports}
    switch_ports = {row["name"]: row for row in switch_ports}
    groups = []

    for port in topology["router_ports"]:
        name = port["name"]
        switch_name = port["switch_port"]
        commands = []
        current = router_ports.get(name)
        if current:
            old_parent = router_parent.get(current["_uuid"])
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
                    *port.get("networks", []),
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
                    port.get("options", {}),
                ),
            ]
        )

        current = switch_ports.get(switch_name)
        if current:
            old_parent = switch_parent.get(current["_uuid"])
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

    for port in topology["localnet_ports"]:
        name = port["name"]
        commands = []
        current = switch_ports.get(name)
        if current:
            old_parent = switch_parent.get(current["_uuid"])
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


def _configure_gateway_chassis(topology, router_ports, gateway_chassis):
    parent = _references(router_ports, "gateway_chassis")
    current = {row["name"]: row for row in gateway_chassis}
    groups = []
    for index, assignment in enumerate(topology["gateway_chassis"]):
        name = assignment["id"]
        row = current.get(name)
        commands = []
        if row:
            old_parent = parent.get(row["_uuid"])
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


def _configure_routes(topology, routers, routes, owner):
    parent = _references(routers, "static_routes")
    current = _identified(routes)
    groups = []
    for index, route in enumerate(topology["static_routes"]):
        row = current.get(route["id"])
        commands = []
        if row:
            old_parent = parent.get(row["_uuid"])
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


def _configure_nat(topology, routers, rules, owner):
    parent = _references(routers, "nat")
    current = _identified(rules)
    groups = []
    for index, rule in enumerate(topology["nat_rules"]):
        row = current.get(rule["id"])
        commands = []
        if row:
            old_parent = parent.get(row["_uuid"])
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


def _cleanup(topology, owner, state):
    desired = topology["managed"]
    desired_switch_ports = {
        port["switch_port"] for port in topology["router_ports"]
    } | {port["name"] for port in topology["localnet_ports"]}
    desired_routes = {route["id"] for route in topology["static_routes"]}
    desired_nat = {rule["id"] for rule in topology["nat_rules"]}
    desired_gateway = {item["id"] for item in topology["gateway_chassis"]}
    groups = []

    gateway_parent = _references(state["router_ports"], "gateway_chassis")
    for row in state["gateway_chassis"]:
        if row["name"].startswith(f"{owner}:") and row["name"] not in desired_gateway:
            groups.append(
                [
                    [
                        "remove",
                        "Logical_Router_Port",
                        gateway_parent[row["_uuid"]],
                        "gateway_chassis",
                        row["_uuid"],
                    ]
                ]
            )

    for row in _managed(state["switch_ports"], owner):
        if row["name"] not in desired_switch_ports:
            groups.append([["--if-exists", "lsp-del", row["name"]]])
    for row in _managed(state["router_ports"], owner):
        if row["name"] not in desired["router_ports"]:
            groups.append([["--if-exists", "lrp-del", row["name"]]])

    router_route_parent = _references(state["routers"], "static_routes")
    for row in state["routes"]:
        external_ids = row.get("external_ids", {})
        if (
            external_ids.get(SCOPE) == owner
            and external_ids.get(IDENTIFIER) not in desired_routes
        ):
            groups.append(
                [
                    [
                        "remove",
                        "Logical_Router",
                        router_route_parent[row["_uuid"]],
                        "static_routes",
                        row["_uuid"],
                    ]
                ]
            )

    router_nat_parent = _references(state["routers"], "nat")
    for row in _managed(state["nat"], owner):
        if row.get("external_ids", {}).get(IDENTIFIER) not in desired_nat:
            groups.append(
                [
                    [
                        "remove",
                        "Logical_Router",
                        router_nat_parent[row["_uuid"]],
                        "nat",
                        row["_uuid"],
                    ]
                ]
            )

    for row in _managed(state["switches"], owner):
        if row["name"] not in desired["switches"]:
            groups.append([["--if-exists", "ls-del", row["name"]]])
    for row in _managed(state["routers"], owner):
        if row["name"] not in desired["routers"]:
            groups.append([["--if-exists", "lr-del", row["name"]]])
    _batch(groups)


def _record_removed(topology, state):
    expected = topology["southbound"]
    previous_datapaths = {
        row["name"]
        for table in ("switches", "routers")
        for row in _managed(state[table], topology["owner"])
    }
    previous_ports = {
        row["name"] for row in _managed(state["switch_ports"], topology["owner"])
    }
    expected["absent_datapaths"] = sorted(
        previous_datapaths - set(expected["datapaths"])
    )
    expected["absent_ports"] = sorted(previous_ports - set(expected["ports"]))


def apply(topology):
    owner = topology["owner"]
    topology["southbound"]["started_ns"] = time.monotonic_ns()
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
    state = {
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
                "workers": len(topology["workers"]),
                "switches": len(topology["switches"]),
                "routers": len(topology["routers"]),
            }
        )
    )


def main():
    path = Path(os.environ["OVN_SCALE_TOPOLOGY_PATH"])
    topology = json.loads(path.read_text())
    apply(topology)
    path.write_text(json.dumps(topology))


if __name__ == "__main__":
    main()
