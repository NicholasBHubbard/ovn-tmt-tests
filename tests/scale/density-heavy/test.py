import os
from pathlib import Path

import pytest

from ovn_test.command import Runner
from ovn_test.config import read_bool, read_int, read_list
from ovn_test.scale import ScaleBaseline, verify_scale_environment
from ovn_test.topology import Topology
from ovn_test.workload import (
    Workload,
    load_scale_topology,
    validate_heavy,
)


@pytest.fixture
def workload():
    topology = Topology.from_environment()
    runner = Runner(topology)
    computes = verify_scale_environment(runner, topology)
    scale_topology = load_scale_topology(
        os.environ["OTT_SCALE_TOPOLOGY_PATH"],
        computes,
    )
    initial = read_int(os.environ, "OTT_SCALE_INITIAL_PODS", 11000)
    total = read_int(os.environ, "OTT_SCALE_TOTAL_PODS", 11250)
    base_per_worker = read_int(os.environ, "OTT_SCALE_BASE_PODS_PER_WORKER", 10)
    pods_per_service = read_int(os.environ, "OTT_SCALE_PODS_PER_SERVICE", 2)
    sync_timeout = read_int(os.environ, "OTT_SCALE_SYNC_TIMEOUT", 1800)
    if base_per_worker < 0:
        raise ValueError("base pods per worker must be non-negative")
    if pods_per_service < 1:
        raise ValueError("pods per service must be positive")
    if sync_timeout < 1:
        raise ValueError("scale sync timeout must be positive")
    measured = total - initial
    if measured % pods_per_service:
        raise ValueError("measured pods must contain complete services")
    config = {
        "initial": initial,
        "iterations": measured // pods_per_service,
        "pods_per_service": pods_per_service,
        "protocols": read_list(os.environ, "OTT_SCALE_LB_PROTOCOLS", "tcp,udp,sctp"),
        "timeout": read_int(os.environ, "OTT_SCALE_TIMEOUT", 60),
        "ipv4": read_bool(os.environ, "OTT_SCALE_IPV4", True),
        "ipv6": read_bool(os.environ, "OTT_SCALE_IPV6", True),
        "mtu": read_int(os.environ, "OTT_SCALE_MTU", 1342),
        "chassis": len(computes),
    }
    validate_heavy(**config)
    config["workers"] = len(scale_topology["workers"])
    config["total"] = total
    config["base_per_worker"] = base_per_worker
    config["sync_timeout"] = sync_timeout
    baseline = ScaleBaseline(
        runner,
        computes,
        scale_topology,
        os.environ["TMT_TEST_DATA"],
        base_per_worker,
        config["protocols"],
        config["ipv4"],
        config["ipv6"],
        config["mtu"],
        config["timeout"],
        config["sync_timeout"],
        "density-heavy-base",
        "dhb",
    )
    instance = Workload(
        runner,
        computes,
        "density-heavy",
        "dh",
        Path(os.environ["TMT_TEST_DATA"]) / "metrics.csv",
        ipv4=config["ipv4"],
        ipv6=config["ipv6"],
        mtu=config["mtu"],
        timeout=config["timeout"],
        sync_timeout=config["sync_timeout"],
        scale_topology=scale_topology,
        base_ports_per_worker=base_per_worker,
    )
    try:
        baseline.create()
        yield instance, config, baseline.external
    finally:
        try:
            instance.cleanup()
        finally:
            baseline.cleanup()
        instance.verify_cleanup()
        baseline.verify_cleanup()


def test_density_heavy(workload):
    instance, config, external = workload
    instance.measure("startup", "namespace", instance.create_namespace)

    def add_service_group(service, first_pod, phase, passive=False):
        def create_group():
            active = list(range(first_pod, first_pod + config["pods_per_service"]))
            for index in active:
                instance.add_endpoint(
                    index,
                    phase,
                    passive=passive,
                    converge=False,
                )
            instance.add_service(service, first_pod, config["protocols"])
            if not passive:
                for position, index in enumerate(active):
                    instance.verify_connectivity(
                        index,
                        active[(position + 1) % len(active)],
                    )
                    external.verify(instance.endpoint(index))

        instance.measure(
            service,
            phase,
            create_group,
        )

    service = 0
    for first_pod in range(0, config["initial"], config["pods_per_service"]):
        add_service_group(service, first_pod, "startup", passive=True)
        service += 1
    instance.sync()

    for iteration in range(config["iterations"]):
        first_pod = config["initial"] + iteration * config["pods_per_service"]
        add_service_group(service + iteration, first_pod, "iteration")
    instance.sync()

    print(
        f"Density-heavy passed with {config['initial']} initial pods, "
        f"{config['total']} total pods, "
        f"{config['base_per_worker']} base pods per worker, "
        f"{config['iterations']} measured service groups and "
        f"{config['pods_per_service']} pods per service across "
        f"{config['workers']} workers on {config['chassis']} chassis, "
        "including external gateway connectivity."
    )
    print(f"Metrics: {instance.metrics_file}")
