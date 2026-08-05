import os
from collections.abc import Iterator
from functools import partial
from pathlib import Path
from typing import Any, Callable

import pytest
from ovn_test.cluster_density import (
    add_namespace_services,
    validate_cluster_density,
)
from ovn_test.command import Runner
from ovn_test.config import read_bool, read_int, read_list
from ovn_test.namespace import NamespaceResources, OvnNamespace
from ovn_test.ovsdb import Ovsdb
from ovn_test.scale import ScaleBaseline, verify_scale_environment
from ovn_test.scale_topology import ScaleTopology
from ovn_test.topology import Topology
from ovn_test.workload import Workload


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
