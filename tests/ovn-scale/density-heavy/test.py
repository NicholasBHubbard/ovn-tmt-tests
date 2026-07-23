import os
from pathlib import Path

import pytest

from ovn_test.command import Runner
from ovn_test.config import read_bool, read_int, read_list
from ovn_test.topology import Topology
from ovn_test.workload import (
    Workload,
    validate_heavy,
)


@pytest.fixture
def workload():
    topology = Topology.from_environment()
    computes = topology.role("compute")
    config = {
        "initial": read_int(os.environ, "OTT_SCALE_INITIAL_PODS", 4),
        "iterations": read_int(os.environ, "OTT_SCALE_ITERATIONS", 2),
        "pods_per_service": read_int(os.environ, "OTT_SCALE_PODS_PER_SERVICE", 2),
        "protocols": read_list(os.environ, "OTT_SCALE_LB_PROTOCOLS", "tcp,udp,sctp"),
        "timeout": read_int(os.environ, "OTT_SCALE_TIMEOUT", 60),
        "ipv4": read_bool(os.environ, "OTT_SCALE_IPV4", True),
        "ipv6": read_bool(os.environ, "OTT_SCALE_IPV6", True),
        "mtu": read_int(os.environ, "OTT_SCALE_MTU", 1342),
        "chassis": len(computes),
    }
    validate_heavy(**config)
    instance = Workload(
        Runner(topology),
        computes,
        "density-heavy",
        "dh",
        Path(os.environ["TMT_TEST_DATA"]) / "metrics.csv",
        ipv4=config["ipv4"],
        ipv6=config["ipv6"],
        mtu=config["mtu"],
        timeout=config["timeout"],
    )
    yield instance, config
    instance.cleanup()
    instance.verify_cleanup()


def test_density_heavy(workload):
    instance, config = workload
    instance.measure("startup", "topology", instance.create_topology)

    def add_service_group(service, first_pod, phase):
        for index in range(first_pod, first_pod + config["pods_per_service"]):
            instance.add_endpoint(index, phase)

        def create_service():
            instance.add_service(service, first_pod, config["protocols"])
            instance.sync()

        instance.measure(
            service,
            f"{phase}_service",
            create_service,
        )

    service = 0
    for first_pod in range(0, config["initial"], config["pods_per_service"]):
        add_service_group(service, first_pod, "startup")
        service += 1
    for index in range(config["initial"]):
        instance.verify_connectivity(index)

    for iteration in range(config["iterations"]):
        first_pod = config["initial"] + iteration * config["pods_per_service"]
        add_service_group(service + iteration, first_pod, "iteration")
        for index in range(first_pod, first_pod + config["pods_per_service"]):
            instance.verify_connectivity(index)

    print(
        f"Density-heavy passed with {config['initial']} initial pods, "
        f"{config['iterations']} measured service groups and "
        f"{config['pods_per_service']} pods per service across "
        f"{config['chassis']} chassis."
    )
    print(f"Metrics: {instance.metrics_file}")
