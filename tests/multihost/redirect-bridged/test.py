from typing import Callable

import pytest
from ovn_test.network import Network
from ovn_test.ovsdb import Ovsdb

pytestmark = pytest.mark.usefixtures("setup_scenario")


def test_redirect_bridged_traffic(
    nb: Ovsdb, sb: Ovsdb, network: Callable[[str], Network]
) -> None:
    options = nb.mapping("Logical_Router_Port", "options", "name=rr-public")
    assert options["redirect-type"] == "bridged"

    gateway = sb.value("Chassis", "_uuid", "name=gateway-1")
    redirect = sb.value(
        "Port_Binding",
        "chassis",
        "logical_port=cr-rr-public",
    )
    assert redirect == gateway

    network("compute-1").wait_for_ping("rr-vm1", "20.10.0.2")
