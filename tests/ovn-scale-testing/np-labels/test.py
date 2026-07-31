import os
from collections.abc import Callable, Iterator
from functools import partial
from pathlib import Path
from typing import Any

import pytest
from ovn_test.command import Runner
from ovn_test.config import read_bool, read_int, read_list
from ovn_test.namespace import OvnNamespace
from ovn_test.scale import ScaleBaseline, verify_scale_environment
from ovn_test.topology import Topology
from ovn_test.workload import Workload, load_scale_topology


def label_groups(total: int, count: int) -> list[list[int]]:
    return [
        [index for index in range(total) if index % count == label]
        for label in range(count)
    ]


def local_label_index(namespace: int, label: int, pods: int, labels: int) -> int:
    start = namespace * pods
    return next(
        index for index in range(start, start + pods) if index % labels == label
    )


def target_indexes(
    mode: str,
    namespace: int,
    label: int,
    pods: int,
    groups: list[list[int]],
) -> list[int]:
    next_label = (label + 1) % len(groups)
    if mode == "large":
        return groups[next_label]
    start = namespace * pods
    excluded = {label, next_label}
    return [
        index
        for index in range(start, start + pods)
        if index % len(groups) not in excluded
    ]


def validate_config(config: dict[str, Any]) -> None:
    positive = (
        "namespaces",
        "pods_per_namespace",
        "labels",
        "timeout",
        "sync_timeout",
        "workers",
        "chassis",
    )
    if any(
        isinstance(config[name], bool)
        or not isinstance(config[name], int)
        or config[name] < 1
        for name in positive
    ):
        raise ValueError(
            "namespace, pod, label, timeout, worker and chassis counts must be positive"
        )
    if config["mode"] not in {"small", "large"}:
        raise ValueError("label policy mode must be small or large")
    if config["labels"] <= 2 or config["pods_per_namespace"] < config["labels"]:
        raise ValueError(
            "label policies need at least three labels represented in every namespace"
        )
    if (
        isinstance(config["base_pods"], bool)
        or not isinstance(config["base_pods"], int)
        or config["base_pods"] < 0
    ):
        raise ValueError("base pods per worker must be non-negative")
    if not config["protocols"] or len(config["protocols"]) != len(
        set(config["protocols"])
    ):
        raise ValueError("load-balancer protocols must be unique")
    if set(config["protocols"]) - {"tcp", "udp", "sctp"}:
        raise ValueError("load-balancer protocols must be tcp, udp or sctp")
    if not isinstance(config["ipv4"], bool) or not isinstance(config["ipv6"], bool):
        raise ValueError("IP family settings must be booleans")
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
    config["total_pods"] = config["namespaces"] * config["pods_per_namespace"]
    if config["labels"] >= config["total_pods"]:
        raise ValueError("label count must be smaller than the total pod count")
    if config["total_pods"] > 65534:
        raise ValueError("label-policy workload exceeds its endpoint identity space")


@pytest.fixture
def workload() -> Iterator[Any]:
    topology = Topology.from_environment()
    runner = Runner(topology)
    computes = verify_scale_environment(runner, topology)
    scale_topology = load_scale_topology(
        os.environ["OTT_SCALE_TOPOLOGY_PATH"],
        computes,
    )
    config: dict[str, Any] = {
        "mode": os.environ.get("OTT_SCALE_LABEL_MODE", "small"),
        "namespaces": read_int(os.environ, "OTT_SCALE_NAMESPACES", 2),
        "pods_per_namespace": read_int(os.environ, "OTT_SCALE_PODS_PER_NAMESPACE", 16),
        "labels": read_int(os.environ, "OTT_SCALE_LABELS", 4),
        "base_pods": read_int(os.environ, "OTT_SCALE_BASE_PODS_PER_WORKER", 2),
        "deny_priority": read_int(os.environ, "OTT_SCALE_POLICY_DENY_PRIORITY", 1),
        "control_priority": read_int(
            os.environ,
            "OTT_SCALE_POLICY_CONTROL_PRIORITY",
            2,
        ),
        "allow_priority": read_int(os.environ, "OTT_SCALE_POLICY_ALLOW_PRIORITY", 3),
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
    mode = config["mode"]
    prefix = f"np{mode[0]}"
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
        f"np-{mode}-base",
        f"{prefix}b",
    )
    instance = Workload(
        runner,
        computes,
        f"np-{mode}",
        prefix,
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
        yield instance, namespaces, config
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


def test_np_labels(workload: Any) -> None:
    instance, namespaces, config = workload
    pods = config["pods_per_namespace"]

    def create_namespace(namespace: OvnNamespace, index: int) -> None:
        namespace.create()
        endpoints = [
            instance.add_endpoint(index * pods + offset, "startup", converge=False)
            for offset in range(pods)
        ]
        namespace.add_endpoints(endpoints)
        for family, enabled in ((4, config["ipv4"]), (6, config["ipv6"])):
            if enabled:
                namespace.default_deny(
                    family,
                    config["deny_priority"],
                    config["control_priority"],
                )

    for index in range(config["namespaces"]):
        namespace = OvnNamespace(
            instance.runner,
            instance.name,
            f"ns_netpol_{config['mode']}_{index}",
            index,
            ipv4=config["ipv4"],
            ipv6=config["ipv6"],
        )
        namespaces.append(namespace)
        instance.measure(index, "startup", partial(create_namespace, namespace, index))
    instance.sync()

    groups = label_groups(config["total_pods"], config["labels"])

    def apply_policy(namespace: OvnNamespace, namespace_index: int, label: int) -> None:
        source = groups[label]
        target = target_indexes(config["mode"], namespace_index, label, pods, groups)
        source_name = f"source-{label}"
        target_name = f"target-{label}"
        namespace.set_group(
            source_name, [instance.endpoints[index] for index in source]
        )
        namespace.set_group(
            target_name, [instance.endpoints[index] for index in target]
        )
        for family, enabled in ((4, config["ipv4"]), (6, config["ipv6"])):
            if enabled:
                namespace.allow_between(
                    source_name,
                    target_name,
                    family,
                    config["allow_priority"],
                )

    for namespace_index, namespace in enumerate(namespaces):
        for label in range(config["labels"]):
            iteration = namespace_index * config["labels"] + label
            instance.measure(
                iteration,
                f"policy_{config['mode']}",
                partial(apply_policy, namespace, namespace_index, label),
            )
    instance.sync()

    for namespace_index in range(config["namespaces"]):
        for label in range(config["labels"]):
            source = local_label_index(
                namespace_index,
                label,
                pods,
                config["labels"],
            )
            if config["mode"] == "small":
                target = target_indexes("small", namespace_index, label, pods, groups)[
                    0
                ]
            else:
                target = local_label_index(
                    (namespace_index + 1) % config["namespaces"],
                    (label + 1) % config["labels"],
                    pods,
                    config["labels"],
                )
            instance.verify_connectivity(source, target)

    print(
        f"NP-{config['mode']} passed with {config['namespaces']} namespaces, "
        f"{pods} pods per namespace and {config['labels']} labels across "
        f"{config['workers']} workers on {config['chassis']} chassis."
    )
    print(f"Metrics: {instance.metrics_file}")
