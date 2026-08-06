import ipaddress
import os
from collections.abc import Iterator, Mapping, Sequence
from functools import partial
from pathlib import Path
from typing import Any

import pytest
from ovn_test.command import Runner
from ovn_test.config import read_bool, read_int, read_list
from ovn_test.load_balancer import socket
from ovn_test.scale import ScaleBaseline, verify_scale_environment
from ovn_test.scale_topology import ScaleTopology
from ovn_test.topology import Topology
from ovn_test.workload import Workload


def cluster_vip(iteration: int, family: int) -> str:
    network = ipaddress.ip_network("90.0.0.0/8" if family == 4 else "9::/32")
    return str(network[iteration + 1])


def worker_vip(worker: Mapping[str, Any], family: int) -> str:
    try:
        network = ipaddress.ip_network(worker["external"][f"ipv{family}"])
    except (KeyError, ValueError) as error:
        raise ValueError(
            f"worker {worker.get('name', '<unknown>')} has no valid IPv{family} "
            "external network"
        ) from error
    return str(network[-2])


def validate_config(config: dict[str, Any]) -> None:
    for name in (
        "iterations",
        "backends",
        "timeout",
        "sync_timeout",
        "workers",
        "chassis",
    ):
        value = config[name]
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ValueError(f"{name} must be a positive integer")
    base_pods = config["base_pods"]
    if isinstance(base_pods, bool) or not isinstance(base_pods, int) or base_pods < 0:
        raise ValueError("base pods per worker must be non-negative")
    protocols = config["protocols"]
    if not protocols or len(protocols) != len(set(protocols)):
        raise ValueError("load-balancer protocols must be unique")
    if set(protocols) - {"tcp", "udp", "sctp"}:
        raise ValueError("load-balancer protocols must be tcp, udp or sctp")
    if not isinstance(config["ipv4"], bool) or not isinstance(config["ipv6"], bool):
        raise ValueError("IP family settings must be booleans")
    if not config["ipv4"] and not config["ipv6"]:
        raise ValueError("at least one IP family must be enabled")
    minimum_mtu = 1280 if config["ipv6"] else 576
    if not minimum_mtu <= config["mtu"] <= 65535:
        raise ValueError(f"MTU must be between {minimum_mtu} and 65535")
    config["total_pods"] = config["iterations"] * (config["backends"] + 1)
    if config["total_pods"] > 65534:
        raise ValueError("service-route workload exceeds its endpoint identity space")


def add_service_routes(
    workload: Workload,
    iteration: int,
    endpoints: Sequence[dict[str, Any]],
    protocols: Sequence[str],
) -> None:
    if workload.load_balancer_group_uuid is None:
        raise RuntimeError("service routes require a load-balancer group")
    for family, enabled in (
        (4, workload.ipv4_enabled),
        (6, workload.ipv6_enabled),
    ):
        if not enabled:
            continue
        suffix = "6" if family == 6 else ""
        backends = [
            socket(endpoint[f"ipv{family}"], 8080, family) for endpoint in endpoints[1:]
        ]
        for protocol in protocols:
            workload.replace_load_balancer(
                f"slb{suffix}-cluster-{iteration}-{protocol}",
                protocol,
                {socket(cluster_vip(iteration, family), 80, family): backends},
                group=workload.load_balancer_group_uuid,
            )
            for worker in workload.workers:
                workload.replace_load_balancer(
                    f"slb{suffix}-node-{iteration}-{worker['name']}-{protocol}",
                    protocol,
                    {socket(worker_vip(worker, family), 80, family): backends},
                    switches=[worker["switch"]],
                    routers=[worker["gateway_router"]],
                )


@pytest.fixture
def workload(request: pytest.FixtureRequest) -> Iterator[Any]:
    topology = Topology.from_environment()
    runner = Runner(topology)
    computes = verify_scale_environment(runner, topology)
    scale = ScaleTopology.from_environment(runner, computes, os.environ)
    request.addfinalizer(scale.cleanup)  # noqa: PT021
    scale_topology = scale.create()
    integration_bridge = os.environ.get("OTT_INTEGRATION_BRIDGE", "br-int")
    config: dict[str, Any] = {
        "iterations": read_int(os.environ, "OTT_SCALE_SERVICE_LOAD_BALANCERS", 16),
        "backends": read_int(os.environ, "OTT_SCALE_SERVICE_BACKENDS", 4),
        "base_pods": read_int(os.environ, "OTT_SCALE_BASE_PODS_PER_WORKER", 2),
        "protocols": read_list(os.environ, "OTT_SCALE_LB_PROTOCOLS", "tcp,udp,sctp"),
        "timeout": read_int(os.environ, "OTT_SCALE_TIMEOUT", 60),
        "sync_timeout": read_int(os.environ, "OTT_SCALE_SYNC_TIMEOUT", 1800),
        "ipv4": read_bool(os.environ, "OTT_SCALE_IPV4", True),
        "ipv6": read_bool(os.environ, "OTT_SCALE_IPV6", True),
        "mtu": read_int(os.environ, "OTT_SCALE_MTU", 1342),
        "workers": len(scale_topology["workers"]),
        "chassis": len(computes),
    }
    validate_config(config)
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
        name="service-route-base",
        prefix="srb",
        integration_bridge=integration_bridge,
    )
    instance = Workload(
        runner,
        computes,
        "service-route",
        "sr",
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
    try:
        baseline.create()
        yield instance, config
    finally:
        try:
            instance.cleanup()
        finally:
            baseline.cleanup()
        instance.verify_cleanup()
        baseline.verify_cleanup()


def test_service_route(workload: Any) -> None:
    instance, config = workload
    instance.measure("startup", "namespace", instance.create_namespace)
    group_size = config["backends"] + 1

    def create_service(iteration: int) -> None:
        first = iteration * group_size
        endpoints = [
            instance.add_endpoint(index, "service_route", converge=False)
            for index in range(first, first + group_size)
        ]
        add_service_routes(instance, iteration, endpoints, config["protocols"])

    for iteration in range(config["iterations"]):
        instance.measure(
            iteration,
            "service_route",
            partial(create_service, iteration),
        )
    instance.sync()
    for iteration in range(config["iterations"]):
        client = iteration * group_size
        instance.verify_connectivity(client, client + 1)

    families = int(config["ipv4"]) + int(config["ipv6"])
    load_balancers = (
        config["iterations"]
        * families
        * len(config["protocols"])
        * (config["workers"] + 1)
    )
    print(
        f"Service-route passed with {config['iterations']} service groups, "
        f"{config['backends']} backends per service and {load_balancers} load "
        f"balancers across {config['workers']} workers on "
        f"{config['chassis']} chassis."
    )
    print(f"Metrics: {instance.metrics_file}")
