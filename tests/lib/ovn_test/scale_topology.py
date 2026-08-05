import ipaddress
from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any, Optional, TypedDict, Union

from ovn_test._scale_topology_apply import apply as _apply_topology
from ovn_test.command import Runner
from ovn_test.config import read_bool, read_int
from ovn_test.ovsdb import Ovsdb

Network = Union[ipaddress.IPv4Network, ipaddress.IPv6Network]


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

    result["load_balancer_groups"] = [
        {
            "id": load_balancer_group,
            "switches": [worker["switch"] for worker in result["workers"]],
            "routers": [worker["gateway_router"] for worker in result["workers"]],
        }
    ]
    result["load_balancer_group"] = load_balancer_group
    _unique([item["name"] for item in result["switches"]], "logical switch names")
    _unique([item["name"] for item in result["routers"]], "logical router names")
    _unique(
        [item["name"] for item in result["router_ports"]],
        "logical router port names",
    )
    _unique(
        [item["switch_port"] for item in result["router_ports"]]
        + [item["name"] for item in result["localnet_ports"]],
        "logical switch port names",
    )
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
        _apply_topology(self.runner, data)
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
            "load_balancer_groups": [],
            "load_balancer_group": group,
            "managed": {"switches": [], "routers": [], "router_ports": []},
            "southbound": {
                "datapaths": [],
                "ports": [],
                "absent_datapaths": [],
                "absent_ports": [],
            },
        }
        first_error = None
        try:
            _apply_topology(self.runner, empty)
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
