import os
from pathlib import Path

import pytest

from ovn_test.command import Runner
from ovn_test.config import read_bool, read_int
from ovn_test.topology import Topology
from ovn_test.workload import (
    Workload,
    validate_light,
)


@pytest.fixture
def workload():
    topology = Topology.from_environment()
    computes = topology.role("compute")
    config = {
        "initial": read_int(os.environ, "OTT_SCALE_INITIAL_PORTS", 2),
        "iterations": read_int(os.environ, "OTT_SCALE_ITERATIONS", 3),
        "timeout": read_int(os.environ, "OTT_SCALE_TIMEOUT", 60),
        "ipv4": read_bool(os.environ, "OTT_SCALE_IPV4", True),
        "ipv6": read_bool(os.environ, "OTT_SCALE_IPV6", True),
        "mtu": read_int(os.environ, "OTT_SCALE_MTU", 1342),
        "chassis": len(computes),
    }
    validate_light(**config)
    instance = Workload(
        Runner(topology),
        computes,
        "density-light",
        "dl",
        Path(os.environ["TMT_TEST_DATA"]) / "metrics.csv",
        ipv4=config["ipv4"],
        ipv6=config["ipv6"],
        mtu=config["mtu"],
        timeout=config["timeout"],
    )
    yield instance, config
    instance.cleanup()
    instance.verify_cleanup()


def test_density_light(workload):
    instance, config = workload
    instance.measure("startup", "topology", instance.create_topology)

    for index in range(config["initial"]):
        instance.add_endpoint(index, "startup")
    for index in range(config["initial"]):
        instance.verify_connectivity(index)

    first = config["initial"]
    for index in range(first, first + config["iterations"]):
        instance.add_endpoint(index, "iteration")
        instance.verify_connectivity(index)

    print(
        f"Scale workload passed with {config['initial']} initial ports and "
        f"{config['iterations']} measured iterations across "
        f"{config['chassis']} chassis."
    )
    print(f"Metrics: {instance.metrics_file}")
