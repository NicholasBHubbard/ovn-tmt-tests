import ipaddress
import json
import time
from collections import Counter
from collections.abc import Mapping, Sequence
from hashlib import sha256
from typing import Any, Optional, TypedDict, Union

from ovn_test.command import Runner
from ovn_test.config import read_bool, read_int
from ovn_test.ovsdb import Ovsdb

Network = Union[ipaddress.IPv4Network, ipaddress.IPv6Network]

OWNER = "ovn-tmt-tests-owner"
IDENTIFIER = "ovn-tmt-tests-id"
SCOPE = "ovn-tmt-tests-scope"
GROUP_OWNER = "ovn-tmt-tests-load-balancer-group-owner"


class Family(TypedDict):
    version: int
    internal: Network
    external: Network
    join: Network
    cluster: Network
    default: str


def _next(network: Network, index: int) -> Network:
    address = int(network.network_address) + index * network.num_addresses
    if network.version == 4:
        return ipaddress.IPv4Network((address, network.prefixlen))
    return ipaddress.IPv6Network((address, network.prefixlen))


def _address(network: Network, index: int) -> str:
    address = network[index]
    return f"{address}/{network.prefixlen}"


def _mac(kind: int, index: int) -> str:
    octets = (kind, index >> 16 & 255, index >> 8 & 255, index & 255)
    return "02:00:" + ":".join(f"{octet:02x}" for octet in octets)


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} must be a non-empty string")
    return value


def _network(value: object, version: int, label: str) -> Network:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be an IPv{version} network")
    try:
        network = ipaddress.ip_network(value)
    except ValueError as error:
        raise ValueError(f"{label} must be an IPv{version} network") from error
    if network.version != version:
        raise ValueError(f"{label} must be an IPv{version} network")
    return network


def _unique(values: Sequence[Any], label: str) -> None:
    if len(values) != len(set(values)):
        raise ValueError(f"{label} must be unique")


def generate(config: dict[str, Any]) -> dict[str, Any]:
    count = config["worker_count"]
    if isinstance(count, bool) or not isinstance(count, int) or count < 1:
        raise ValueError("worker_count must be a positive integer")

    workers = config["workers"]
    if not isinstance(workers, list) or not all(
        isinstance(name, str) and name for name in workers
    ):
        raise ValueError("workers must be a list of non-empty names")
    prefix = _text(config["worker_prefix"], "worker_prefix")
    names = workers or [f"{prefix}-{index}" for index in range(count)]
    chassis = config["chassis"]
    if len(names) != len(set(names)):
        raise ValueError("workers must contain unique names")
    if (
        not isinstance(chassis, list)
        or len(chassis) != len(set(chassis))
        or not all(isinstance(name, str) and name for name in chassis)
    ):
        raise ValueError("chassis must contain unique non-empty names")
    if not isinstance(config["ipv4"], bool) or not isinstance(config["ipv6"], bool):
        raise ValueError("ipv4 and ipv6 must be booleans")
    if not config["ipv4"] and not config["ipv6"]:
        raise ValueError("at least one IP family must be enabled")

    worker_chassis = [
        chassis[index % len(chassis)] if chassis else name
        for index, name in enumerate(names)
    ]
    workers_per_chassis = Counter(worker_chassis)
    for chassis_name, worker_count in workers_per_chassis.items():
        if worker_count > 4094:
            raise ValueError(f"chassis {chassis_name} exceeds its external VLAN space")
    next_vlan = Counter()

    families: list[Family] = []
    for version in (4, 6):
        if not config[f"ipv{version}"]:
            continue
        internal = _network(
            config[f"internal_ipv{version}"], version, f"internal_ipv{version}"
        )
        external = _network(
            config[f"external_ipv{version}"], version, f"external_ipv{version}"
        )
        join = _network(config[f"join_ipv{version}"], version, f"join_ipv{version}")
        cluster = _network(
            config[f"cluster_ipv{version}"], version, f"cluster_ipv{version}"
        )
        if internal.num_addresses < 2:
            raise ValueError(f"internal_ipv{version} is too small")
        if external.num_addresses < 3:
            raise ValueError(f"external_ipv{version} is too small")
        if join.num_addresses < len(names) + 2:
            raise ValueError(f"join_ipv{version} is too small for the workers")
        try:
            _next(internal, len(names) - 1)
            _next(external, len(names) - 1)
        except ValueError as error:
            raise ValueError(
                f"IPv{version} worker networks exceed the address family"
            ) from error
        families.append(
            {
                "version": version,
                "internal": internal,
                "external": external,
                "join": join,
                "cluster": cluster,
                "default": "0.0.0.0/0" if version == 4 else "::/0",
            }
        )

    owner = _text(config["id"], "id")
    cluster_router = _text(config["cluster_router"], "cluster_router")
    join_switch = _text(config["join_switch"], "join_switch")
    load_balancer_group = _text(config["load_balancer_group"], "load_balancer_group")
    physical_bridge = _text(config["physical_bridge"], "physical_bridge")
    physical_network = _text(config["physical_network"], "physical_network")
    snat_ct_zone = config.get("snat_ct_zone", "")
    if snat_ct_zone != "":
        if isinstance(snat_ct_zone, bool):
            raise ValueError("snat_ct_zone must be between 0 and 65535")
        try:
            snat_ct_zone = int(snat_ct_zone)
        except (TypeError, ValueError) as error:
            raise ValueError("snat_ct_zone must be between 0 and 65535") from error
        if not 0 <= snat_ct_zone <= 65535:
            raise ValueError("snat_ct_zone must be between 0 and 65535")
    cluster_join_port = f"rtr-to-{join_switch}"
    result: dict[str, Any] = {
        "owner": owner,
        "physical_bridge": physical_bridge,
        "physical_network": physical_network,
        "switches": [{"name": join_switch}],
        "routers": [
            {
                "name": cluster_router,
                "options": {"always_learn_from_arp_request": "false"},
            }
        ],
        "router_ports": [
            {
                "name": cluster_join_port,
                "router": cluster_router,
                "switch": join_switch,
                "switch_port": f"{join_switch}-to-rtr",
                "mac": _mac(0, 0),
                "networks": [_address(family["join"], -2) for family in families],
            }
        ],
        "gateway_chassis": [],
        "localnet_ports": [],
        "static_routes": [],
        "nat_rules": [],
        "workers": [],
    }

    for index, (name, chassis_name) in enumerate(zip(names, worker_chassis)):
        worker_switch = f"lswitch-{name}"
        gateway_router = f"gwrouter-{name}"
        external_switch = f"ext-{name}"
        cluster_worker_port = f"rtr-to-node-{name}"
        gateway_join_port = f"gw-to-join-{name}"
        gateway_external_port = f"gw-to-ext-{name}"
        external_vlan = None
        if workers_per_chassis[chassis_name] > 1:
            next_vlan[chassis_name] += 1
            external_vlan = next_vlan[chassis_name]
        worker = {
            "name": name,
            "chassis": chassis_name,
            "switch": worker_switch,
            "gateway_router": gateway_router,
            "external_switch": external_switch,
            "internal": {},
            "external": {},
            "join": {},
        }
        if external_vlan is not None:
            worker["external_vlan"] = external_vlan

        result["switches"].extend([{"name": worker_switch}, {"name": external_switch}])
        gateway_options = {
            "always_learn_from_arp_request": "false",
            "dynamic_neigh_routers": "true",
            "chassis": chassis_name,
            "lb_force_snat_ip": "router_ip",
        }
        if snat_ct_zone != "":
            gateway_options["snat-ct-zone"] = snat_ct_zone
        result["routers"].append(
            {
                "name": gateway_router,
                "options": gateway_options,
            }
        )

        internal_networks = []
        external_networks = []
        join_networks = []
        for family in families:
            version = family["version"]
            internal = _next(family["internal"], index)
            external = _next(family["external"], index)
            join = family["join"]
            internal_router = _address(internal, -2)
            external_router = _address(external, -2)
            external_host = str(external[-3])
            cluster_join = str(join[-2])
            gateway_join = str(join[-index - 3])

            worker["internal"][f"ipv{version}"] = str(internal)
            worker["external"][f"ipv{version}"] = str(external)
            worker["join"][f"ipv{version}"] = gateway_join
            internal_networks.append(internal_router)
            external_networks.append(external_router)
            join_networks.append(f"{gateway_join}/{join.prefixlen}")

            result["static_routes"].extend(
                [
                    {
                        "id": f"{owner}:{name}:cluster-v{version}",
                        "router": gateway_router,
                        "prefix": str(family["cluster"]),
                        "nexthop": cluster_join,
                    },
                    {
                        "id": f"{owner}:{name}:default-v{version}",
                        "router": gateway_router,
                        "prefix": family["default"],
                        "nexthop": external_host,
                    },
                    {
                        "id": f"{owner}:{name}:worker-v{version}",
                        "router": cluster_router,
                        "prefix": str(internal),
                        "nexthop": gateway_join,
                        "policy": "src-ip",
                    },
                ]
            )
            result["nat_rules"].append(
                {
                    "id": f"{owner}:{name}:snat-v{version}",
                    "router": gateway_router,
                    "type": "snat",
                    "external_ip": gateway_join,
                    "logical_ip": str(family["cluster"]),
                }
            )

        result["router_ports"].extend(
            [
                {
                    "name": cluster_worker_port,
                    "router": cluster_router,
                    "switch": worker_switch,
                    "switch_port": f"node-to-rtr-{name}",
                    "mac": _mac(1, index),
                    "networks": internal_networks,
                },
                {
                    "name": gateway_join_port,
                    "router": gateway_router,
                    "switch": join_switch,
                    "switch_port": f"join-to-gw-{name}",
                    "mac": _mac(2, index),
                    "networks": join_networks,
                },
                {
                    "name": gateway_external_port,
                    "router": gateway_router,
                    "switch": external_switch,
                    "switch_port": f"ext-to-gw-{name}",
                    "mac": _mac(3, index),
                    "networks": external_networks,
                },
            ]
        )
        result["gateway_chassis"].append(
            {
                "id": f"{owner}:{cluster_worker_port}:{name}",
                "router_port": cluster_worker_port,
                "chassis": chassis_name,
                "priority": 10,
            }
        )
        localnet: dict[str, Any] = {
            "name": f"provnet-{name}",
            "switch": external_switch,
            "network": physical_network,
        }
        if external_vlan is not None:
            localnet["tag"] = external_vlan
        result["localnet_ports"].append(localnet)
        result["workers"].append(worker)

    result["load_balancer_group"] = load_balancer_group
    switch_names = [item["name"] for item in result["switches"]]
    router_names = [item["name"] for item in result["routers"]]
    router_port_names = [item["name"] for item in result["router_ports"]]
    switch_port_names = [item["switch_port"] for item in result["router_ports"]] + [
        item["name"] for item in result["localnet_ports"]
    ]
    for names, label in (
        (switch_names, "logical switch names"),
        (router_names, "logical router names"),
        (router_port_names, "logical router port names"),
        (switch_port_names, "logical switch port names"),
    ):
        _unique(names, label)
    result["southbound"] = {
        "datapaths": switch_names + router_names,
        "ports": switch_port_names,
        "absent_datapaths": [],
        "absent_ports": [],
    }
    return result


def _names(value: str) -> list[str]:
    if not value.strip():
        return []
    names = [item.strip() for item in value.split(",")]
    if any(not name for name in names):
        raise ValueError("OTT_SCALE_WORKER_NAMES contains an empty name")
    return names


def configuration(
    computes: Sequence[str],
    environment: Mapping[str, str],
) -> dict[str, Any]:
    return {
        "id": environment.get("OTT_SCALE_ID", "ovn-scale"),
        "worker_count": read_int(environment, "OTT_SCALE_WORKERS", 2),
        "worker_prefix": environment.get("OTT_SCALE_WORKER_PREFIX", "ovn-scale"),
        "workers": _names(environment.get("OTT_SCALE_WORKER_NAMES", "")),
        "chassis": list(computes),
        "ipv4": read_bool(environment, "OTT_SCALE_IPV4", True),
        "ipv6": read_bool(environment, "OTT_SCALE_IPV6", True),
        "internal_ipv4": environment.get("OTT_SCALE_INTERNAL_IPV4", "16.0.0.0/16"),
        "internal_ipv6": environment.get("OTT_SCALE_INTERNAL_IPV6", "16::/64"),
        "external_ipv4": environment.get("OTT_SCALE_EXTERNAL_IPV4", "20.0.0.0/16"),
        "external_ipv6": environment.get("OTT_SCALE_EXTERNAL_IPV6", "20::/64"),
        "join_ipv4": environment.get("OTT_SCALE_JOIN_IPV4", "30.0.0.0/16"),
        "join_ipv6": environment.get("OTT_SCALE_JOIN_IPV6", "30::/64"),
        "cluster_ipv4": environment.get("OTT_SCALE_CLUSTER_IPV4", "16.0.0.0/4"),
        "cluster_ipv6": environment.get("OTT_SCALE_CLUSTER_IPV6", "16::/32"),
        "cluster_router": environment.get("OTT_SCALE_CLUSTER_ROUTER", "lr-cluster1"),
        "join_switch": environment.get("OTT_SCALE_JOIN_SWITCH", "ls-join1"),
        "load_balancer_group": environment.get(
            "OTT_SCALE_LOAD_BALANCER_GROUP", "cluster-lb-group1"
        ),
        "snat_ct_zone": environment.get("OTT_SCALE_SNAT_CT_ZONE", ""),
        "physical_network": environment.get("OTT_COMPUTE_PHYSICAL_NETWORK", "physnet"),
        "physical_bridge": environment.get("OTT_COMPUTE_PHYSICAL_BRIDGE", "br-ex"),
    }


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


def _move_reference(
    commands: list[list[Any]],
    table: str,
    old_parent: Optional[str],
    new_parent: str,
    column: str,
    uuid: str,
) -> None:
    if old_parent != new_parent:
        commands.extend(
            [
                ["remove", table, old_parent, column, uuid],
                ["add", table, new_parent, column, uuid],
            ]
        )


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
            _move_reference(
                commands,
                "Logical_Router",
                router_parent.get(current["_uuid"]),
                port["router"],
                "ports",
                current["_uuid"],
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
            _move_reference(
                commands,
                "Logical_Switch",
                switch_parent.get(current["_uuid"]),
                port["switch"],
                "ports",
                current["_uuid"],
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
            _move_reference(
                commands,
                "Logical_Switch",
                switch_parent.get(current["_uuid"]),
                port["switch"],
                "ports",
                current["_uuid"],
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
        values = [
            f"name={_quoted(name)}",
            f"chassis_name={_quoted(assignment['chassis'])}",
            f"priority={assignment.get('priority', 0)}",
            _external_id(OWNER, topology["owner"]),
        ]
        if row:
            _move_reference(
                commands,
                "Logical_Router_Port",
                parent.get(row["_uuid"]),
                assignment["router_port"],
                "gateway_chassis",
                row["_uuid"],
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
                        *values,
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
                    *values,
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
        values = [
            f"ip_prefix={_quoted(route['prefix'])}",
            f"nexthop={_quoted(route['nexthop'])}",
            f"policy={_quoted(route.get('policy', 'dst-ip'))}",
            f"route_table={_quoted(route.get('route_table', ''))}",
            f"output_port={_quoted(route.get('output_port', []))}",
            _external_id(IDENTIFIER, route["id"]),
            _external_id(SCOPE, owner),
        ]
        if row:
            _move_reference(
                commands,
                "Logical_Router",
                parent.get(row["_uuid"]),
                route["router"],
                "static_routes",
                row["_uuid"],
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
                        *values,
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
                    *values,
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
        values = [
            f"type={_quoted(rule['type'])}",
            f"external_ip={_quoted(rule['external_ip'])}",
            f"logical_ip={_quoted(rule['logical_ip'])}",
            _external_id(IDENTIFIER, rule["id"]),
            _external_id(OWNER, owner),
        ]
        if row:
            _move_reference(
                commands,
                "Logical_Router",
                parent.get(row["_uuid"]),
                rule["router"],
                "nat",
                row["_uuid"],
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
                        *values,
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
                    *values,
                ]
            )
        groups.append(commands)
    db.batch(groups)


def _cleanup(
    db: _Database, topology: dict[str, Any], owner: str, state: dict[str, Any]
) -> None:
    desired_switches = {item["name"] for item in topology["switches"]}
    desired_routers = {item["name"] for item in topology["routers"]}
    desired_router_ports = {item["name"] for item in topology["router_ports"]}
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
        if row["name"] not in desired_router_ports:
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
        if row["name"] not in desired_switches:
            groups.append([["--if-exists", "ls-del", row["name"]]])
    for row in _managed(state["routers"], owner):
        if row["name"] not in desired_routers:
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

    state = {
        "switches": db.rows("Logical_Switch", "_uuid", "name", "external_ids", "ports"),
        "routers": db.rows(
            "Logical_Router",
            "_uuid",
            "name",
            "external_ids",
            "ports",
            "static_routes",
            "nat",
        ),
        "router_ports": db.rows(
            "Logical_Router_Port",
            "_uuid",
            "name",
            "external_ids",
            "gateway_chassis",
        ),
        "switch_ports": db.rows("Logical_Switch_Port", "_uuid", "name", "external_ids"),
        "routes": db.rows("Logical_Router_Static_Route", "_uuid", "external_ids"),
        "nat": db.rows("NAT", "_uuid", "external_ids"),
        "gateway_chassis": db.rows("Gateway_Chassis", "_uuid", "name", "external_ids"),
    }

    _reject_collisions(
        state["router_ports"],
        [item["name"] for item in topology["router_ports"]],
        owner,
        "logical router port",
    )
    _reject_collisions(
        state["switch_ports"],
        [item["switch_port"] for item in topology["router_ports"]]
        + [item["name"] for item in topology["localnet_ports"]],
        owner,
        "logical switch port",
    )
    _reject_collisions(
        state["gateway_chassis"],
        [item["id"] for item in topology["gateway_chassis"]],
        owner,
        "gateway chassis",
    )

    _configure_ports(
        db,
        topology,
        owner,
        state["routers"],
        state["switches"],
        state["router_ports"],
        state["switch_ports"],
    )
    _configure_gateway_chassis(
        db, topology, state["router_ports"], state["gateway_chassis"]
    )
    _configure_routes(db, topology, state["routers"], state["routes"], owner)
    _configure_nat(db, topology, state["routers"], state["nat"], owner)
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


def _apply(runner: Runner, topology: dict[str, Any]) -> None:
    workers = topology["workers"]
    group = topology["load_balancer_group"]
    if workers:
        _apply_database(runner, topology)
        _apply_load_balancer_group(
            runner,
            group,
            [worker["switch"] for worker in workers],
            [worker["gateway_router"] for worker in workers],
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
            group,
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


class ScaleTopology:
    def __init__(
        self,
        runner: Runner,
        config: dict[str, Any],
        *,
        wait: bool = True,
        timeout: int = 120,
    ) -> None:
        if isinstance(timeout, bool) or not isinstance(timeout, int) or timeout < 1:
            raise ValueError("scale topology timeout must be a positive integer")
        if not isinstance(wait, bool):
            raise ValueError("scale topology wait must be a boolean")
        self.runner = runner
        self.config = config
        self.wait = wait
        self.timeout = timeout
        self.data: Optional[dict[str, Any]] = None

    @classmethod
    def from_environment(
        cls,
        runner: Runner,
        computes: Sequence[str],
        environment: Mapping[str, str],
    ) -> "ScaleTopology":
        timeout = read_int(
            environment,
            "OTT_SCALE_TOPOLOGY_TIMEOUT",
            environment.get("OTT_SCALE_SYNC_TIMEOUT", 120),
        )
        return cls(
            runner,
            configuration(computes, environment),
            wait=read_bool(environment, "OTT_SCALE_WAIT_FOR_SB", True),
            timeout=timeout,
        )

    def create(self, worker_count: Optional[int] = None) -> dict[str, Any]:
        config = self.config
        if worker_count is not None:
            config = {**config, "worker_count": worker_count, "workers": []}
        data = generate(config)
        self.data = data
        _apply(self.runner, data)
        if self.wait:
            self._converge(data["southbound"])
        return data

    def cleanup(self) -> None:
        if self.data is None:
            return
        group = self.data["load_balancer_group"]
        empty = {
            "owner": self.data["owner"],
            "workers": [],
            "switches": [],
            "routers": [],
            "router_ports": [],
            "localnet_ports": [],
            "gateway_chassis": [],
            "static_routes": [],
            "nat_rules": [],
            "load_balancer_group": group,
            "southbound": {
                "datapaths": [],
                "ports": [],
                "absent_datapaths": [],
                "absent_ports": [],
            },
        }
        first_error = None
        try:
            _apply(self.runner, empty)
        except Exception as error:
            first_error = error
        if self.wait:
            try:
                self._converge(empty["southbound"])
            except Exception as error:
                if first_error is None:
                    first_error = error
        if first_error is not None:
            raise first_error
        self.data = None

    def _converge(self, expected: dict[str, Any]) -> None:
        self.runner.run(
            "ovn-nbctl",
            "--wait=sb",
            f"--timeout={self.timeout}",
            "sync",
        )
        sb = Ovsdb(self.runner, "ovn-sbctl")
        actual = {
            "datapaths": {
                item.get("name")
                for item in sb.values("Datapath_Binding", "external_ids")
            }
            - {None},
            "ports": set(sb.values("Port_Binding", "logical_port")),
        }
        problems = {}
        for kind in ("datapaths", "ports"):
            if missing := set(expected[kind]) - actual[kind]:
                problems[f"missing_{kind}"] = sorted(missing)
            if stale := set(expected[f"absent_{kind}"]) & actual[kind]:
                problems[f"stale_{kind}"] = sorted(stale)
        if problems:
            raise RuntimeError(f"Southbound topology did not converge: {problems}")
