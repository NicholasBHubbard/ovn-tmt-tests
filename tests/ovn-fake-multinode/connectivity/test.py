import pytest


pytestmark = pytest.mark.usefixtures("setup_scenario")


def test_switching_acls_and_routing(runner, network):
    compute_1 = network("compute-1")
    compute_2 = network("compute-2")
    assert compute_1.namespace_exists("sw0p1")
    assert compute_2.namespace_exists("sw0p2")
    assert compute_2.namespace_exists("sw1p1")

    compute_1.wait_for_ping("sw0p1", "10.0.0.4")
    runner.run("ovn-nbctl", "pg-add", "pg0", "sw0-port1", "sw0-port2")
    runner.run(
        "ovn-nbctl",
        "acl-add",
        "pg0",
        "to-lport",
        "1001",
        "outport == @pg0 && ip4",
        "drop",
    )
    runner.run("ovn-nbctl", "--wait=sb", "sync")
    assert not compute_1.ping("sw0p1", "10.0.0.4", count=2)

    runner.run(
        "ovn-nbctl",
        "acl-add",
        "pg0",
        "to-lport",
        "1002",
        "outport == @pg0 && ip4 && icmp",
        "allow-related",
    )
    runner.run("ovn-nbctl", "--wait=sb", "sync")
    compute_1.wait_for_ping("sw0p1", "10.0.0.4")
    compute_1.wait_for_ping("sw0p1", "20.0.0.3")

    runner.run("ovn-nbctl", "lsp-set-addresses", "sw1-port1", "unknown")
    runner.run("ovn-nbctl", "--wait=hv", "sync")
    compute_1.wait_for_ping("sw0p1", "20.0.0.3")
