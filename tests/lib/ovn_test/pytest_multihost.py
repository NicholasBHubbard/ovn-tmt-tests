import pytest

from ovn_test.ansible import Ansible
from ovn_test.command import Runner
from ovn_test.network import Network
from ovn_test.ovsdb import Ovsdb
from ovn_test.topology import Topology


@pytest.fixture(scope="session")
def topology():
    return Topology.from_environment()


@pytest.fixture(scope="session")
def runner(topology):
    return Runner(topology)


@pytest.fixture(scope="session")
def ansible(topology):
    return Ansible.from_environment(topology)


@pytest.fixture
def setup_scenario(request, ansible):
    ansible.run(request.node.path.parent / "setup.yml")


@pytest.fixture
def network(runner):
    return lambda guest: Network(runner, guest)


@pytest.fixture
def nb(runner):
    return Ovsdb(runner, "ovn-nbctl")


@pytest.fixture
def sb(runner):
    return Ovsdb(runner, "ovn-sbctl")
