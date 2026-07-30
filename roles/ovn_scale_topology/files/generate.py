import ipaddress
import json
import os
from collections import Counter
from pathlib import Path
from typing import TypedDict, Union, cast

Network = Union[ipaddress.IPv4Network, ipaddress.IPv6Network]


class Family(TypedDict):
    version: int
    internal: str
    external: str
    join: Network
    cluster: str
    default: str


class Config(TypedDict):
    id: str
    worker_count: int
    worker_prefix: str
    workers: list[str]
    chassis: list[str]
    ipv4: bool
    ipv6: bool
    internal_ipv4: str
    internal_ipv6: str
    external_ipv4: str
    external_ipv6: str
    join_ipv4: str
    join_ipv6: str
    cluster_ipv4: str
    cluster_ipv6: str
    cluster_router: str
    join_switch: str
    load_balancer_group: str
    snat_ct_zone: str
    physical_network: str
    physical_bridge: str


class NamedObject(TypedDict):
    name: str


class Router(NamedObject):
    options: dict[str, Union[str, int]]


class RouterPort(NamedObject):
    router: str
    switch: str
    switch_port: str
    mac: str
    networks: list[str]


class GatewayChassis(TypedDict):
    id: str
    router_port: str
    chassis: str
    priority: int


class LocalnetRequired(TypedDict):
    name: str
    switch: str
    network: str


class Localnet(LocalnetRequired, total=False):
    tag: int


class StaticRouteRequired(TypedDict):
    id: str
    router: str
    prefix: str
    nexthop: str


class StaticRoute(StaticRouteRequired, total=False):
    policy: str


class NatRule(TypedDict):
    id: str
    router: str
    type: str
    external_ip: str
    logical_ip: str


class WorkerRequired(TypedDict):
    name: str
    chassis: str
    switch: str
    gateway_router: str
    external_switch: str
    internal: dict[str, str]
    external: dict[str, str]
    join: dict[str, str]


class Worker(WorkerRequired, total=False):
    external_vlan: int


class LoadBalancerGroup(TypedDict):
    id: str
    name: str
    switches: list[str]
    routers: list[str]


class Managed(TypedDict):
    switches: list[str]
    routers: list[str]
    router_ports: list[str]


class Southbound(TypedDict):
    datapaths: list[str]
    ports: list[str]
    absent_datapaths: list[str]
    absent_ports: list[str]


class State(TypedDict, total=False):
    owner: str
    physical_bridge: str
    physical_network: str
    switches: list[NamedObject]
    routers: list[Router]
    router_ports: list[RouterPort]
    gateway_chassis: list[GatewayChassis]
    localnet_ports: list[Localnet]
    static_routes: list[StaticRoute]
    nat_rules: list[NatRule]
    workers: list[Worker]
    load_balancer_groups: list[LoadBalancerGroup]
    load_balancer_group: str
    managed: Managed
    southbound: Southbound


def _next(network: str, index: int) -> Network:
    parsed = ipaddress.ip_network(network)
    address = int(parsed.network_address) + index * parsed.num_addresses
    return ipaddress.ip_network((address, parsed.prefixlen))


def _address(network: Network, index: int) -> str:
    address = network[index]
    return f"{address}/{network.prefixlen}"


def _mac(kind: int, index: int) -> str:
    octets = (kind, index >> 16 & 255, index >> 8 & 255, index & 255)
    return "02:00:" + ":".join(f"{octet:02x}" for octet in octets)


def generate(config: Config) -> State:
    count = config["worker_count"]
    names = config["workers"] or [
        f"{config['worker_prefix']}-{index}" for index in range(count)
    ]
    chassis = config["chassis"]
    if not names or len(names) != len(set(names)):
        raise ValueError("workers must contain unique names")
    if (
        not isinstance(chassis, list)
        or len(chassis) != len(set(chassis))
        or not all(isinstance(name, str) and name for name in chassis)
    ):
        raise ValueError("chassis must contain unique non-empty names")
    if count < 1:
        raise ValueError("worker_count must be positive")
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
        enabled = config["ipv4"] if version == 4 else config["ipv6"]
        if not enabled:
            continue
        internal = config["internal_ipv4"] if version == 4 else config["internal_ipv6"]
        external = config["external_ipv4"] if version == 4 else config["external_ipv6"]
        join = config["join_ipv4"] if version == 4 else config["join_ipv6"]
        cluster = config["cluster_ipv4"] if version == 4 else config["cluster_ipv6"]
        families.append(
            {
                "version": version,
                "internal": internal,
                "external": external,
                "join": ipaddress.ip_network(join),
                "cluster": cluster,
                "default": "0.0.0.0/0" if version == 4 else "::/0",
            }
        )

    owner = config["id"]
    cluster_router = config["cluster_router"]
    join_switch = config["join_switch"]
    snat_ct_zone: Union[str, int] = config.get("snat_ct_zone", "")
    if snat_ct_zone != "":
        snat_ct_zone = int(snat_ct_zone)
        if not 0 <= snat_ct_zone <= 65535:
            raise ValueError("snat_ct_zone must be between 0 and 65535")
    cluster_join_port = f"rtr-to-{join_switch}"
    result: State = {
        "owner": owner,
        "physical_bridge": config["physical_bridge"],
        "physical_network": config["physical_network"],
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
        worker: Worker = {
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
        gateway_options: dict[str, Union[str, int]] = {
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
                        "prefix": family["cluster"],
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
                    "logical_ip": family["cluster"],
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
        localnet: Localnet = {
            "name": f"provnet-{name}",
            "switch": external_switch,
            "network": config["physical_network"],
        }
        if external_vlan is not None:
            localnet["tag"] = external_vlan
        result["localnet_ports"].append(localnet)
        result["workers"].append(worker)

    result["load_balancer_groups"] = [
        {
            "id": owner,
            "name": config["load_balancer_group"],
            "switches": [worker["switch"] for worker in result["workers"]],
            "routers": [worker["gateway_router"] for worker in result["workers"]],
        }
    ]
    result["load_balancer_group"] = config["load_balancer_group"]
    result["managed"] = {
        "switches": [item["name"] for item in result["switches"]],
        "routers": [item["name"] for item in result["routers"]],
        "router_ports": [item["name"] for item in result["router_ports"]],
    }
    result["southbound"] = {
        "datapaths": result["managed"]["switches"] + result["managed"]["routers"],
        "ports": [item["switch_port"] for item in result["router_ports"]]
        + [item["name"] for item in result["localnet_ports"]],
        "absent_datapaths": [],
        "absent_ports": [],
    }
    return result


def main() -> None:
    output = json.dumps(
        generate(cast(Config, json.loads(os.environ["OVN_SCALE_TOPOLOGY_CONFIG"])))
    )
    path = os.environ.get("OVN_SCALE_TOPOLOGY_OUTPUT")
    if path:
        Path(path).write_text(output)
    else:
        print(output)


if __name__ == "__main__":
    main()
