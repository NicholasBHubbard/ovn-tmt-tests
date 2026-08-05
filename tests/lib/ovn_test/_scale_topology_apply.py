import json
import time
from collections.abc import Mapping, Sequence
from hashlib import sha256
from typing import Any

from ovn_test.command import Runner
from ovn_test.ovsdb import Ovsdb

OWNER = "ovn-tmt-tests-owner"
IDENTIFIER = "ovn-tmt-tests-id"
SCOPE = "ovn-tmt-tests-scope"
GROUP_OWNER = "ovn-tmt-tests-load-balancer-group-owner"


class _Database:
    def __init__(self, runner: Runner) -> None:
        self.runner = runner
        self.ovsdb = Ovsdb(runner, "ovn-nbctl")

    def run(self, *args: object) -> str:
        return self.runner.output("ovn-nbctl", *args)

    def rows(self, table: str, *columns: str) -> list[dict[str, Any]]:
        return self.ovsdb.find(table, columns=columns)

    def batch(self, groups: Sequence[Any], size: int = 50) -> None:
        for offset in range(0, len(groups), size):
            arguments = []
            for group in groups[offset : offset + size]:
                for command in group:
                    if arguments:
                        arguments.append("--")
                    arguments.extend(command)
            if arguments:
                self.run(*arguments)


def _references(rows: Sequence[dict[str, Any]], column: str) -> dict[str, str]:
    result = {}
    for row in rows:
        values = row[column]
        values = values if isinstance(values, list) else [values]
        result.update({value: row["name"] for value in values if value})
    return result


def _quoted(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"))


def _external_id(key: str, value: Any) -> str:
    return f"external_ids:{key}={_quoted(value)}"


def _option_value(value: object) -> str:
    return str(value).lower() if isinstance(value, bool) else str(value)


def _options(
    table: str, name: str, column: str, values: Mapping[str, Any]
) -> list[list[str]]:
    commands = [["clear", table, name, column]]
    commands.extend(
        [
            "set",
            table,
            name,
            f"{column}:{key}={_quoted(_option_value(value))}",
        ]
        for key, value in values.items()
    )
    return commands


def _managed(rows: Sequence[dict[str, Any]], owner: str) -> list[dict[str, Any]]:
    return [row for row in rows if row.get("external_ids", {}).get(OWNER) == owner]


def _identified(rows: Sequence[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {
        row.get("external_ids", {}).get(IDENTIFIER): row
        for row in rows
        if row.get("external_ids", {}).get(IDENTIFIER)
    }


def _reject_collisions(
    rows: Sequence[dict[str, Any]],
    names: Sequence[str],
    owner: str,
    label: str,
) -> None:
    wanted = set(names)
    found = {}
    for row in rows:
        name = row["name"]
        if name not in wanted:
            continue
        if name in found:
            raise RuntimeError(f"{label} {name!r} is not unique")
        found[name] = row
        if row.get("external_ids", {}).get(OWNER) != owner:
            raise RuntimeError(f"{label} {name!r} is not owned by {owner!r}")


def _configure_roots(db: _Database, topology: dict[str, Any], owner: str) -> None:
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
    db.batch(groups)


def _configure_ports(
    db: _Database,
    topology: dict[str, Any],
    owner: str,
    routers: Sequence[dict[str, Any]],
    switches: Sequence[dict[str, Any]],
    router_ports: Sequence[dict[str, Any]],
    switch_ports: Sequence[dict[str, Any]],
) -> None:
    router_parent = _references(routers, "ports")
    switch_parent = _references(switches, "ports")
    router_ports_by_name = {row["name"]: row for row in router_ports}
    switch_ports_by_name = {row["name"]: row for row in switch_ports}
    groups = []

    for port in topology["router_ports"]:
        name = port["name"]
        switch_name = port["switch_port"]
        commands = []
        current = router_ports_by_name.get(name)
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

        current = switch_ports_by_name.get(switch_name)
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
        current = switch_ports_by_name.get(name)
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

    db.batch(groups)


def _configure_gateway_chassis(
    db: _Database,
    topology: dict[str, Any],
    router_ports: Sequence[dict[str, Any]],
    gateway_chassis: Sequence[dict[str, Any]],
) -> None:
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
                        _external_id(OWNER, topology["owner"]),
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
                    _external_id(OWNER, topology["owner"]),
                ]
            )
        groups.append(commands)
    db.batch(groups)


def _configure_routes(
    db: _Database,
    topology: dict[str, Any],
    routers: Sequence[dict[str, Any]],
    routes: Sequence[dict[str, Any]],
    owner: str,
) -> None:
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
    db.batch(groups)


def _configure_nat(
    db: _Database,
    topology: dict[str, Any],
    routers: Sequence[dict[str, Any]],
    rules: Sequence[dict[str, Any]],
    owner: str,
) -> None:
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
    db.batch(groups)


def _cleanup(
    db: _Database, topology: dict[str, Any], owner: str, state: dict[str, Any]
) -> None:
    desired = topology["managed"]
    desired_switch_ports = {
        port["switch_port"] for port in topology["router_ports"]
    } | {port["name"] for port in topology["localnet_ports"]}
    desired_routes = {route["id"] for route in topology["static_routes"]}
    desired_nat = {rule["id"] for rule in topology["nat_rules"]}
    desired_gateway = {item["id"] for item in topology["gateway_chassis"]}
    groups = []

    gateway_parent = _references(state["router_ports"], "gateway_chassis")
    for row in _managed(state["gateway_chassis"], owner):
        if row["name"] not in desired_gateway:
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
    db.batch(groups)


def _record_removed(topology: dict[str, Any], state: dict[str, Any]) -> None:
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


def _group_owner_key(name: str) -> str:
    digest = sha256(name.encode()).hexdigest()
    return f"{GROUP_OWNER}-{digest}"


def _apply_load_balancer_group(
    runner: Runner,
    name: str,
    switches: Sequence[str],
    routers: Sequence[str],
    owner: str,
    *,
    present: bool = True,
) -> None:
    db = _Database(runner)
    owner_key = _group_owner_key(name)
    global_rows = db.rows("NB_Global", "external_ids")
    if len(global_rows) != 1:
        raise RuntimeError(f"expected one NB_Global row, found {len(global_rows)}")
    claimed_by = global_rows[0]["external_ids"].get(owner_key)
    matches = [
        row
        for row in db.rows("Load_Balancer_Group", "_uuid", "name")
        if row["name"] == name
    ]
    if len(matches) > 1:
        raise RuntimeError(f"load balancer group {name!r} is not unique")
    if matches and claimed_by != owner:
        raise RuntimeError(f"load balancer group {name!r} is not owned by {owner!r}")
    if claimed_by not in (None, owner):
        raise RuntimeError(f"load balancer group {name!r} is not owned by {owner!r}")
    if not matches and not present:
        if claimed_by == owner:
            db.batch(
                [
                    [
                        ["remove", "NB_Global", ".", "external_ids", owner_key],
                    ]
                ]
            )
        return

    commands = []
    if matches:
        target = matches[0]["_uuid"]
        current_switches = {
            row["name"]
            for row in db.rows("Logical_Switch", "name", "load_balancer_group")
            if target in row["load_balancer_group"]
        }
        current_routers = {
            row["name"]
            for row in db.rows("Logical_Router", "name", "load_balancer_group")
            if target in row["load_balancer_group"]
        }
    else:
        target = "@group"
        current_switches = set()
        current_routers = set()
        commands.extend(
            [
                [
                    "--id=@group",
                    "create",
                    "Load_Balancer_Group",
                    f"name={_quoted(name)}",
                ],
                ["set", "NB_Global", ".", _external_id(owner_key, owner)],
            ]
        )

    wanted_switches = set(switches) if present else set()
    wanted_routers = set(routers) if present else set()
    commands.extend(
        ["remove", "Logical_Switch", item, "load_balancer_group", target]
        for item in sorted(current_switches - wanted_switches)
    )
    commands.extend(
        ["add", "Logical_Switch", item, "load_balancer_group", target]
        for item in sorted(wanted_switches - current_switches)
    )
    commands.extend(
        ["remove", "Logical_Router", item, "load_balancer_group", target]
        for item in sorted(current_routers - wanted_routers)
    )
    commands.extend(
        ["add", "Logical_Router", item, "load_balancer_group", target]
        for item in sorted(wanted_routers - current_routers)
    )
    if not present:
        commands.extend(
            [
                ["destroy", "Load_Balancer_Group", target],
                ["remove", "NB_Global", ".", "external_ids", owner_key],
            ]
        )
    db.batch([commands])


def _apply_database(runner: Runner, topology: dict[str, Any]) -> None:
    db = _Database(runner)
    owner = topology["owner"]
    topology["southbound"]["started_ns"] = time.monotonic_ns()

    existing_switches = db.rows("Logical_Switch", "name", "external_ids")
    existing_routers = db.rows("Logical_Router", "name", "external_ids")
    _reject_collisions(
        existing_switches,
        [item["name"] for item in topology["switches"]],
        owner,
        "logical switch",
    )
    _reject_collisions(
        existing_routers,
        [item["name"] for item in topology["routers"]],
        owner,
        "logical router",
    )
    _configure_roots(db, topology, owner)

    switches = db.rows("Logical_Switch", "_uuid", "name", "external_ids", "ports")
    routers = db.rows(
        "Logical_Router",
        "_uuid",
        "name",
        "external_ids",
        "ports",
        "static_routes",
        "nat",
    )
    router_ports = db.rows(
        "Logical_Router_Port",
        "_uuid",
        "name",
        "external_ids",
        "gateway_chassis",
    )
    switch_ports = db.rows("Logical_Switch_Port", "_uuid", "name", "external_ids")
    routes = db.rows("Logical_Router_Static_Route", "_uuid", "external_ids")
    nat = db.rows("NAT", "_uuid", "external_ids")
    gateway_chassis = db.rows("Gateway_Chassis", "_uuid", "name", "external_ids")

    _reject_collisions(
        router_ports,
        [item["name"] for item in topology["router_ports"]],
        owner,
        "logical router port",
    )
    _reject_collisions(
        switch_ports,
        [item["switch_port"] for item in topology["router_ports"]]
        + [item["name"] for item in topology["localnet_ports"]],
        owner,
        "logical switch port",
    )
    _reject_collisions(
        gateway_chassis,
        [item["id"] for item in topology["gateway_chassis"]],
        owner,
        "gateway chassis",
    )

    _configure_ports(
        db,
        topology,
        owner,
        routers,
        switches,
        router_ports,
        switch_ports,
    )
    _configure_gateway_chassis(db, topology, router_ports, gateway_chassis)
    _configure_routes(db, topology, routers, routes, owner)
    _configure_nat(db, topology, routers, nat, owner)
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
        db,
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


def apply(runner: Runner, topology: dict[str, Any]) -> None:
    groups = topology["load_balancer_groups"]
    if len(groups) > 1:
        raise ValueError("scale topology supports one load balancer group")

    if groups:
        group = groups[0]
        if group["id"] != topology["load_balancer_group"]:
            raise ValueError("load balancer group identifiers do not match")
        _apply_database(runner, topology)
        _apply_load_balancer_group(
            runner,
            group["id"],
            group["switches"],
            group["routers"],
            topology["owner"],
        )
        return

    first_error = None
    try:
        _apply_database(runner, topology)
    except Exception as error:
        first_error = error
    try:
        _apply_load_balancer_group(
            runner,
            topology["load_balancer_group"],
            [],
            [],
            topology["owner"],
            present=False,
        )
    except Exception as error:
        if first_error is None:
            first_error = error
    if first_error is not None:
        raise first_error
