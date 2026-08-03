import pytest
from ovn_test.command import Runner
from ovn_test.ovsdb import Ovsdb
from ovn_test.state import Snapshots


@pytest.fixture
def nb() -> Ovsdb:
    return Ovsdb(Runner(), "ovn-nbctl")


@pytest.fixture
def snapshots() -> Snapshots:
    return Snapshots.from_environment()


def assert_group(
    nb: Ovsdb,
    switches: set[str],
    routers: set[str],
) -> str:
    group = nb.by_name("Load_Balancer_Group", "self-group-main", "_uuid")
    assert (
        set(nb.referring_names("Logical_Switch", "load_balancer_group", group["_uuid"]))
        == switches
    )
    assert (
        set(nb.referring_names("Logical_Router", "load_balancer_group", group["_uuid"]))
        == routers
    )
    load_balancer = nb.by_name("Load_Balancer", "self-group-lb", "_uuid")
    assert nb.referring_names(
        "Load_Balancer_Group", "load_balancer", load_balancer["_uuid"]
    ) == ["self-group-main"]
    return group["_uuid"]


class TestInitial:
    def test_invalid_updates_preserved_initial_state(
        self, nb: Ovsdb, snapshots: Snapshots
    ) -> None:
        uuid = assert_group(nb, {"self-group-a"}, {"self-group-a"})
        snapshots.save("load-balancer-group", uuid)
        assert nb.exists("Load_Balancer_Group", 'name="self-group-delete"')


class TestResult:
    def test_group_was_reconfigured_without_replacement(
        self, nb: Ovsdb, snapshots: Snapshots
    ) -> None:
        uuid = assert_group(nb, {"self-group-b"}, {"self-group-b"})
        assert uuid == snapshots.load("load-balancer-group")
        assert not nb.exists("Load_Balancer_Group", 'name="self-group-delete"')
