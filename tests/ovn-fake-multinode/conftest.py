from collections.abc import Callable

import pytest
from ovn_test.ansible import Ansible
from ovn_test.command import Runner
from ovn_test.network import Network
from ovn_test.ovsdb import Ovsdb
from ovn_test.topology import Topology


@pytest.fixture(scope="session")
def topology() -> Topology:
    return Topology.from_environment()


@pytest.fixture(scope="session")
def runner(topology: Topology) -> Runner:
    return Runner(topology)


@pytest.fixture(scope="session")
def ansible(topology: Topology) -> Ansible:
    return Ansible.from_environment(topology)


@pytest.fixture
def setup_scenario(request: pytest.FixtureRequest, ansible: Ansible) -> None:
    ansible.run(request.node.path.parent / "setup.yml")


@pytest.fixture
def network(runner: Runner) -> Callable[[str], Network]:
    return lambda guest: Network(runner, guest)


@pytest.fixture
def nb(runner: Runner) -> Ovsdb:
    return Ovsdb(runner, "ovn-nbctl")


@pytest.fixture
def sb(runner: Runner) -> Ovsdb:
    return Ovsdb(runner, "ovn-sbctl")
