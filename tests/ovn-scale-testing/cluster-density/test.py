import ipaddress
import os
from collections.abc import Iterator, Mapping, Sequence
from functools import partial
from pathlib import Path
from typing import Any, Callable

import pytest
from ovn_test.command import Runner
from ovn_test.config import read_bool, read_int, read_list
from ovn_test.load_balancer import DEFAULT_OPTIONS, VALID_PROTOCOLS, socket
from ovn_test.namespace import NamespaceResources, OvnNamespace
from ovn_test.ovsdb import Ovsdb
from ovn_test.scale import ScaleBaseline, verify_scale_environment
from ovn_test.scale_topology import ScaleTopology
from ovn_test.topology import Topology
from ovn_test.workload import Workload


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
        socket(_vip(ipv4_vip_network, total - 1, 2, 4), vip_port, 4)
        socket("127.0.0.1", backend_port, 4)
    if ipv6:
        socket(_vip(ipv6_vip_network, total - 1, 2, 6), vip_port, 6)
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


@pytest.fixture
def workload(request: pytest.FixtureRequest) -> Iterator[Any]:
    topology = Topology.from_environment()
    runner = Runner(topology)
    computes = verify_scale_environment(runner, topology)
    scale = ScaleTopology.from_environment(runner, computes, os.environ)
    request.addfinalizer(scale.cleanup)  # noqa: PT021
    scale_topology = scale.create()
    config: dict[str, Any] = {
        "startup": read_int(os.environ, "OTT_SCALE_INITIAL_NAMESPACES", 3800),
        "total": read_int(os.environ, "OTT_SCALE_TOTAL_NAMESPACES", 4000),
        "build_pods": read_int(
            os.environ,
            "OTT_SCALE_BUILD_PODS_PER_NAMESPACE",
            6,
        ),
        "test_pods": read_int(
            os.environ,
            "OTT_SCALE_TEST_PODS_PER_NAMESPACE",
            4,
        ),
        "protocols": read_list(
            os.environ,
            "OTT_SCALE_LB_PROTOCOLS",
            "tcp,udp,sctp",
        ),
        "timeout": read_int(os.environ, "OTT_SCALE_TIMEOUT", 60),
        "ipv4": read_bool(os.environ, "OTT_SCALE_IPV4", True),
        "ipv6": read_bool(os.environ, "OTT_SCALE_IPV6", True),
        "mtu": read_int(os.environ, "OTT_SCALE_MTU", 1342),
        "chassis": len(computes),
        "workers": len(scale_topology["workers"]),
        "base_pods": read_int(
            os.environ,
            "OTT_SCALE_BASE_PODS_PER_WORKER",
            10,
        ),
        "sync_timeout": read_int(
            os.environ,
            "OTT_SCALE_SYNC_TIMEOUT",
            1800,
        ),
        "ipv4_vip_network": os.environ.get(
            "OTT_SCALE_SERVICE_VIP_IPV4_NETWORK", "30.0.0.0/16"
        ),
        "ipv6_vip_network": os.environ.get(
            "OTT_SCALE_SERVICE_VIP_IPV6_NETWORK", "30::/32"
        ),
        "vip_port": read_int(os.environ, "OTT_SCALE_SERVICE_VIP_PORT", 80),
        "backend_port": read_int(os.environ, "OTT_SCALE_SERVICE_BACKEND_PORT", 8080),
    }
    validate_cluster_density(
        **{key: value for key, value in config.items() if key != "sync_timeout"}
    )
    if config["sync_timeout"] < 1:
        raise ValueError("scale sync timeout must be positive")
    integration_bridge = os.environ.get("OTT_INTEGRATION_BRIDGE", "br-int")

    baseline = ScaleBaseline(
        runner,
        computes,
        scale_topology,
        os.environ["TMT_TEST_DATA"],
        pods_per_worker=config["base_pods"],
        protocols=config["protocols"],
        ipv4=config["ipv4"],
        ipv6=config["ipv6"],
        mtu=config["mtu"],
        timeout=config["timeout"],
        sync_timeout=config["sync_timeout"],
        name="cluster-density-base",
        prefix="cdb",
        integration_bridge=integration_bridge,
    )
    instance = Workload(
        runner,
        computes,
        "cluster-density",
        "cd",
        Path(os.environ["TMT_TEST_DATA"]) / "metrics.csv",
        ipv4=config["ipv4"],
        ipv6=config["ipv6"],
        mtu=config["mtu"],
        timeout=config["timeout"],
        sync_timeout=config["sync_timeout"],
        scale_topology=scale_topology,
        base_ports_per_worker=config["base_pods"],
        integration_bridge=integration_bridge,
    )
    group = Ovsdb(runner, "ovn-nbctl").by_name(
        "Load_Balancer_Group",
        scale_topology["load_balancer_group"],
        "_uuid",
    )["_uuid"]
    namespaces = []

    try:
        baseline.create()
        yield instance, namespaces, config, group, baseline
    finally:
        first_error = None

        def attempt(action: Callable[..., Any]) -> None:
            nonlocal first_error
            try:
                action()
            except Exception as error:
                if first_error is None:
                    first_error = error

        for namespace in namespaces:
            attempt(namespace.cleanup)
        attempt(instance.cleanup)
        attempt(baseline.cleanup)
        if first_error is not None:
            raise first_error
        for namespace in namespaces:
            namespace.verify_cleanup()
        instance.verify_cleanup()
        baseline.verify_cleanup()


def test_cluster_density(workload: Any) -> None:
    instance, namespaces, config, group, baseline = workload
    resources = NamespaceResources(instance.runner, instance.name)
    next_endpoint = 0

    def add_pods(count: int, phase: str, passive: bool) -> list[dict[str, Any]]:
        nonlocal next_endpoint
        endpoints = []
        for _ in range(count):
            endpoints.append(
                instance.add_endpoint(
                    next_endpoint,
                    phase,
                    passive=passive,
                    converge=False,
                )
            )
            next_endpoint += 1
        return endpoints

    def create_namespace(
        namespace: OvnNamespace,
        phase: str,
        passive: bool,
    ) -> None:
        namespace.create()
        build = (
            add_pods(config["build_pods"], phase, passive=False) if not passive else []
        )
        if build:
            namespace.add_endpoints(build)

        service = add_pods(config["test_pods"], phase, passive)
        namespace.add_endpoints(service)
        add_namespace_services(
            namespace,
            service,
            config["protocols"],
            group,
            ipv4_vip_network=config["ipv4_vip_network"],
            ipv6_vip_network=config["ipv6_vip_network"],
            vip_port=config["vip_port"],
            backend_port=config["backend_port"],
        )

        if not passive:
            for endpoint in [*build, *service]:
                baseline.external.verify(endpoint)
            for endpoint in build:
                instance.remove_endpoint(endpoint)
            namespace.remove_endpoints(build)

    for namespace_index in range(config["total"]):
        phase = "startup" if namespace_index < config["startup"] else "iteration"
        passive = phase == "startup"
        namespace = OvnNamespace(
            instance.runner,
            instance.name,
            f"NS_density_{namespace_index}",
            namespace_index,
            ipv4=config["ipv4"],
            ipv6=config["ipv6"],
            resources=resources,
        )
        namespaces.append(namespace)

        instance.measure(
            namespace_index,
            phase,
            partial(create_namespace, namespace, phase, passive),
        )
        if namespace_index + 1 == config["startup"]:
            instance.sync()

    instance.sync()
    measured = config["total"] - config["startup"]
    print(
        f"Cluster-density passed with {config['startup']} startup namespaces, "
        f"{config['total']} total namespaces, {config['test_pods']} persistent "
        f"test pods per namespace and {config['build_pods']} temporary build "
        f"pods in each of {measured} measured iterations across "
        f"{config['workers']} workers on {config['chassis']} chassis."
    )
    print(f"Metrics: {instance.metrics_file}")
