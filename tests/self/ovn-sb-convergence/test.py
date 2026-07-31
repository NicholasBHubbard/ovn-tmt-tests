import pytest
from ovn_test.command import Runner
from ovn_test.ovsdb import Ovsdb


@pytest.fixture
def sb() -> Ovsdb:
    return Ovsdb(Runner(), "ovn-sbctl")


def southbound_names(sb: Ovsdb) -> tuple[set[str], set[str]]:
    datapaths = {
        external_ids.get("name")
        for external_ids in sb.values("Datapath_Binding", "external_ids")
    }
    ports = set(sb.values("Port_Binding", "logical_port"))
    return datapaths - {None}, ports


class TestPreconditions:
    def test_southbound_database_is_available(self) -> None:
        assert Runner().succeeds("ovn-sbctl", "show")


class TestPresent:
    def test_expected_objects_exist(self, sb: Ovsdb) -> None:
        datapaths, ports = southbound_names(sb)
        assert "self-convergence" in datapaths
        assert "self-convergence-port" in ports


class TestResult:
    def test_removed_objects_are_absent(self, sb: Ovsdb) -> None:
        datapaths, ports = southbound_names(sb)
        assert "self-convergence" not in datapaths
        assert "self-convergence-port" not in ports
