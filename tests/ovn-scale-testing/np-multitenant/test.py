import ipaddress
import os
from collections.abc import Callable, Iterator
from functools import partial
from pathlib import Path
from typing import Any

import pytest
from ovn_test.command import Runner
from ovn_test.config import read_bool, read_int, read_list
from ovn_test.namespace import NamespaceResources, OvnNamespace
from ovn_test.scale import ScaleBaseline, verify_scale_environment
from ovn_test.scale_topology import ScaleTopology
from ovn_test.topology import Topology
from ovn_test.workload import Workload


def parse_ranges(value: str) -> list[tuple[int, int]]:
    items = [item.strip() for item in value.split(",")]
    if items == [""]:
        return []
    if any(not item for item in items):
        raise ValueError("OTT_SCALE_NAMESPACE_RANGES contains an empty range")

    ranges = []
    for item in items:
        try:
            start, pods = (int(field) for field in item.split(":", 1))
        except ValueError as error:
            raise ValueError(
                "OTT_SCALE_NAMESPACE_RANGES must contain start:pods pairs"
            ) from error
        ranges.append((start, pods))
    return sorted(ranges, reverse=True)


def pods_in_namespace(index: int, ranges: list[tuple[int, int]]) -> int:
    return next((pods for start, pods in ranges if index >= start), 1)


def address_range(start: str, count: int, family: int) -> list[str]:
    address = ipaddress.ip_address(start)
    if address.version != family:
        raise ValueError(f"external address range must use IPv{family}")
    address_type = ipaddress.IPv4Address if family == 4 else ipaddress.IPv6Address
    try:
        return [str(address_type(int(address) + offset)) for offset in range(count)]
    except ValueError as error:
        raise ValueError("external address range exceeds its IP family") from error


def validate_config(config: dict[str, Any]) -> None:
    if config["namespaces"] < 1:
        raise ValueError("namespace count must be positive")
    if config["base_pods"] < 0:
        raise ValueError("base pods per worker must be non-negative")
    if any(
        config[name] < 1 for name in ("timeout", "sync_timeout", "workers", "chassis")
    ):
        raise ValueError("timeouts, worker count and chassis count must be positive")
    if config["small_external_count"] < 1 or config["large_external_count"] < 0:
        raise ValueError("external address counts are invalid")
    if not config["protocols"] or len(config["protocols"]) != len(
        set(config["protocols"])
    ):
        raise ValueError("load-balancer protocols must be unique")
    if set(config["protocols"]) - {"tcp", "udp", "sctp"}:
        raise ValueError("load-balancer protocols must be tcp, udp or sctp")
    if not config["ipv4"] and not config["ipv6"]:
        raise ValueError("at least one IP family must be enabled")
    minimum_mtu = 1280 if config["ipv6"] else 576
    if not minimum_mtu <= config["mtu"] <= 65535:
        raise ValueError(f"MTU must be between {minimum_mtu} and 65535")
    deny = config["deny_priority"]
    if not (
        0 <= deny < config["control_priority"] <= 32767
        and deny < config["allow_priority"] <= 32767
    ):
        raise ValueError("control and allow priorities must be higher than deny")

    starts = [start for start, _ in config["ranges"]]
    if len(starts) != len(set(starts)):
        raise ValueError("namespace range starts must be unique")
    if any(
        start < 0 or start >= config["namespaces"] or pods < 1
        for start, pods in config["ranges"]
    ):
        raise ValueError("namespace ranges need a valid start and positive pod count")
    config["total_pods"] = sum(
        pods_in_namespace(index, config["ranges"])
        for index in range(config["namespaces"])
    )
    if config["total_pods"] > 65534:
        raise ValueError("multitenant workload exceeds its endpoint identity space")


@pytest.fixture
def workload(request: pytest.FixtureRequest) -> Iterator[Any]:
    topology = Topology.from_environment()
    runner = Runner(topology)
    computes = verify_scale_environment(runner, topology)
    scale = ScaleTopology.from_environment(runner, computes, os.environ)
    request.addfinalizer(scale.cleanup)  # noqa: PT021
    scale_topology = scale.create()
    config: dict[str, Any] = {
        "namespaces": read_int(os.environ, "OTT_SCALE_NAMESPACES", 500),
        "ranges": parse_ranges(
            os.environ.get(
                "OTT_SCALE_NAMESPACE_RANGES",
                "200:5,480:20,495:100",
            )
        ),
        "base_pods": read_int(
            os.environ,
            "OTT_SCALE_BASE_PODS_PER_WORKER",
            10,
        ),
        "small_external_count": read_int(
            os.environ,
            "OTT_SCALE_EXTERNAL_SMALL_COUNT",
            3,
        ),
        "large_external_count": read_int(
            os.environ,
            "OTT_SCALE_EXTERNAL_LARGE_COUNT",
            20,
        ),
        "deny_priority": read_int(
            os.environ,
            "OTT_SCALE_POLICY_DENY_PRIORITY",
            1,
        ),
        "control_priority": read_int(
            os.environ,
            "OTT_SCALE_POLICY_CONTROL_PRIORITY",
            2,
        ),
        "allow_priority": read_int(
            os.environ,
            "OTT_SCALE_POLICY_ALLOW_PRIORITY",
            3,
        ),
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
    external_addresses = {}
    for family, enabled in ((4, config["ipv4"]), (6, config["ipv6"])):
        if not enabled:
            continue
        external_addresses[family] = {
            "small": address_range(
                os.environ.get(
                    f"OTT_SCALE_EXTERNAL_IPV{family}_SMALL_START",
                    "42.42.42.1" if family == 4 else "42:42:42::1",
                ),
                config["small_external_count"],
                family,
            ),
            "large": address_range(
                os.environ.get(
                    f"OTT_SCALE_EXTERNAL_IPV{family}_LARGE_START",
                    "43.43.43.1" if family == 4 else "43:43:43::1",
                ),
                config["large_external_count"],
                family,
            ),
        }
    config["external_addresses"] = external_addresses

    baseline = ScaleBaseline(
        runner,
        computes,
        scale_topology,
        os.environ["TMT_TEST_DATA"],
        config["base_pods"],
        config["protocols"],
        config["ipv4"],
        config["ipv6"],
        config["mtu"],
        config["timeout"],
        config["sync_timeout"],
        "np-multitenant-base",
        "npmb",
    )
    instance = Workload(
        runner,
        computes,
        "np-multitenant",
        "npm",
        Path(os.environ["TMT_TEST_DATA"]) / "metrics.csv",
        ipv4=config["ipv4"],
        ipv6=config["ipv6"],
        mtu=config["mtu"],
        timeout=config["timeout"],
        sync_timeout=config["sync_timeout"],
        scale_topology=scale_topology,
        base_ports_per_worker=config["base_pods"],
    )
    namespaces: list[OvnNamespace] = []

    try:
        baseline.create()
        yield instance, namespaces, config, baseline
    finally:
        first_error = None

        def attempt(action: Callable[[], object]) -> None:
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


def test_np_multitenant(workload: Any) -> None:
    instance, namespaces, config, baseline = workload
    resources = NamespaceResources(instance.runner, instance.name)
    external = baseline.external
    next_endpoint = 0

    def create_namespace(namespace: OvnNamespace, count: int) -> None:
        nonlocal next_endpoint
        namespace.create()
        endpoints = [
            instance.add_endpoint(
                next_endpoint + offset,
                "namespace",
                converge=False,
            )
            for offset in range(count)
        ]
        next_endpoint += count
        namespace.add_endpoints(endpoints)

        for family, enabled in ((4, config["ipv4"]), (6, config["ipv6"])):
            if not enabled:
                continue
            namespace.default_deny(
                family,
                config["deny_priority"],
                config["control_priority"],
            )
            namespace.allow_within(family, config["allow_priority"])
            namespace.allow_from_external(
                config["external_addresses"][family]["small"],
                family,
                "small",
                config["allow_priority"],
            )
            namespace.allow_from_external(
                [
                    *config["external_addresses"][family]["large"],
                    external.address(endpoints[0], family),
                ],
                family,
                "large",
                config["allow_priority"],
            )

        if len(endpoints) > 1:
            instance.verify_connectivity(
                next_endpoint - count,
                next_endpoint - 1,
            )
        external.verify_inbound(endpoints[0])

    for namespace_index in range(config["namespaces"]):
        namespace = OvnNamespace(
            instance.runner,
            instance.name,
            f"ns_netpol_multitenant_{namespace_index}",
            namespace_index,
            ipv4=config["ipv4"],
            ipv6=config["ipv6"],
            resources=resources,
        )
        namespaces.append(namespace)
        instance.measure(
            namespace_index,
            "namespace",
            partial(
                create_namespace,
                namespace,
                pods_in_namespace(namespace_index, config["ranges"]),
            ),
        )

    instance.sync()
    print(
        f"NP-multitenant passed with {config['namespaces']} namespaces and "
        f"{config['total_pods']} policy-managed pods across "
        f"{config['workers']} workers on {config['chassis']} chassis."
    )
    print(f"Metrics: {instance.metrics_file}")
