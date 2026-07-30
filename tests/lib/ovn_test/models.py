from typing import Optional, TypedDict


class Endpoint(TypedDict, total=False):
    guest: str
    namespace: str
    interface: str
    port: str
    mac: str
    ipv4: str
    ipv6: str
    switch: str
    worker: str
    gateway4: str
    gateway6: str
    prefix4: int
    prefix6: int
    removed: bool


class WorkerRequired(TypedDict):
    name: str
    chassis: str


class Worker(WorkerRequired, total=False):
    switch: str
    gateway_router: str
    internal: dict[str, str]
    external: dict[str, str]
    external_switch: str
    join: dict[str, str]
    external_vlan: int


class NamedObject(TypedDict):
    name: str


class RouterPort(NamedObject):
    switch_port: str


class GatewayChassis(TypedDict):
    chassis: str


class Southbound(TypedDict):
    datapaths: list[str]
    ports: list[str]
    absent_datapaths: list[str]
    absent_ports: list[str]


class ScaleTopologyRequired(TypedDict):
    workers: list[Worker]


class ScaleTopology(ScaleTopologyRequired, total=False):
    owner: str
    physical_bridge: str
    physical_network: str
    load_balancer_group: str
    switches: list[NamedObject]
    routers: list[NamedObject]
    router_ports: list[RouterPort]
    gateway_chassis: list[GatewayChassis]
    localnet_ports: list[NamedObject]
    southbound: Southbound


class ExternalPeerRequired(TypedDict):
    guest: str
    namespace: str
    interface: str
    vlan: Optional[int]


class ExternalPeer(ExternalPeerRequired, total=False):
    ipv4: str
    ipv6: str
    gateway4: str
    gateway6: str
    prefix4: int
    prefix6: int
