import ipaddress
from collections.abc import Mapping, Sequence

from ovn_test.load_balancer import DEFAULT_OPTIONS, VALID_PROTOCOLS, socket
from ovn_test.namespace import OvnNamespace


def validate_cluster_density(
    startup: int,
    total: int,
    build_pods: int,
    test_pods: int,
    protocols: Sequence[str],
    timeout: int,
    ipv4: bool,
    ipv6: bool,
    mtu: int,
    chassis: int,
    workers: int,
    base_pods: int,
    ipv4_vip_network: str = "30.0.0.0/16",
    ipv6_vip_network: str = "30::/32",
    vip_port: int = 80,
    backend_port: int = 8080,
) -> None:
    positive = {
        "total namespaces": total,
        "test pods per namespace": test_pods,
        "timeout": timeout,
        "chassis": chassis,
        "workers": workers,
    }
    if any(
        isinstance(value, bool) or not isinstance(value, int) or value < 1
        for value in positive.values()
    ):
        raise ValueError(
            "namespace, pod, timeout, chassis and worker counts must be positive"
        )
    if any(
        isinstance(value, bool) or not isinstance(value, int) or value < 0
        for value in (startup, build_pods, base_pods)
    ):
        raise ValueError("startup, build pod and base pod counts must be non-negative")
    if startup > total:
        raise ValueError("startup namespaces cannot exceed total namespaces")
    if test_pods < 4:
        raise ValueError(
            "cluster density requires at least four test pods per namespace"
        )
    if chassis < 2:
        raise ValueError("cluster density requires at least two compute chassis")
    if not isinstance(ipv4, bool) or not isinstance(ipv6, bool) or not (ipv4 or ipv6):
        raise ValueError("at least one boolean IP family setting must be enabled")
    minimum_mtu = 1280 if ipv6 else 576
    if (
        isinstance(mtu, bool)
        or not isinstance(mtu, int)
        or not (minimum_mtu <= mtu <= 65535)
    ):
        raise ValueError(f"MTU must be between {minimum_mtu} and 65535")
    if isinstance(protocols, (str, bytes)) or not isinstance(protocols, Sequence):
        raise ValueError("load-balancer protocols must be a sequence")
    if not protocols or any(not isinstance(protocol, str) for protocol in protocols):
        raise ValueError("load-balancer protocols must be strings")
    if len(protocols) != len(set(protocols)):
        raise ValueError("load-balancer protocols must be unique")
    if set(protocols) - VALID_PROTOCOLS:
        raise ValueError("load-balancer protocols must be tcp, udp or sctp")
    endpoint_count = total * test_pods + (total - startup) * build_pods
    if endpoint_count > 65534:
        raise ValueError("cluster density exceeds its endpoint identity space")
    if ipv4:
        socket(_vip(ipv4_vip_network, 0, 0, 4), vip_port, 4)
        socket("127.0.0.1", backend_port, 4)
    if ipv6:
        socket(_vip(ipv6_vip_network, 0, 0, 6), vip_port, 6)
        socket("::1", backend_port, 6)


def _vip(network: str, index: int, position: int, family: int) -> str:
    subnet = ipaddress.ip_network(network)
    if subnet.version != family:
        raise ValueError(f"service VIP network must be IPv{family}")
    value = (
        int(subnet.network_address) + (index + 1) * subnet.num_addresses + position + 1
    )
    if value >= 1 << subnet.max_prefixlen:
        raise ValueError(f"service VIP range exceeds IPv{subnet.version} address space")
    return str(ipaddress.ip_address(value))


def add_namespace_services(
    namespace: OvnNamespace,
    endpoints: Sequence[Mapping[str, object]],
    protocols: Sequence[str],
    group: str,
    *,
    ipv4_vip_network: str = "30.0.0.0/16",
    ipv6_vip_network: str = "30::/32",
    vip_port: int = 80,
    backend_port: int = 8080,
    options: Mapping[str, str] = DEFAULT_OPTIONS,
) -> None:
    if isinstance(endpoints, (str, bytes)) or not isinstance(endpoints, Sequence):
        raise ValueError("namespace service endpoints must be a sequence")
    if len(endpoints) < 4:
        raise ValueError("namespace services require at least four endpoints")
    if any(not isinstance(endpoint, Mapping) for endpoint in endpoints):
        raise ValueError("each namespace service endpoint must be a mapping")
    if (
        isinstance(protocols, (str, bytes))
        or not isinstance(protocols, Sequence)
        or not protocols
        or any(not isinstance(protocol, str) for protocol in protocols)
    ):
        raise ValueError("load-balancer protocols must be a non-empty sequence")
    if len(protocols) != len(set(protocols)) or set(protocols) - VALID_PROTOCOLS:
        raise ValueError(
            "load-balancer protocols must be unique tcp, udp or sctp values"
        )
    backend_groups = (endpoints[:2], endpoints[2:3], endpoints[3:])
    vips = {}
    for family, enabled, network in (
        (4, namespace.ipv4, ipv4_vip_network),
        (6, namespace.ipv6, ipv6_vip_network),
    ):
        if not enabled:
            continue
        for position, backends in enumerate(backend_groups):
            vips[
                socket(
                    _vip(network, namespace.index, position, family), vip_port, family
                )
            ] = [
                socket(str(endpoint[f"ipv{family}"]), backend_port, family)
                for endpoint in backends
            ]
    for protocol in protocols:
        namespace.replace_load_balancer(
            f"lb_{namespace.name}-{protocol}",
            protocol,
            vips,
            group=group,
            options=options,
        )
