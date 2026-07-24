import pytest


pytestmark = pytest.mark.usefixtures("setup_scenario")


def test_neighbor_advertisements_on_nonresident_chassis(runner, network):
    def wait_for_binding(address):
        runner.wait(
            "ovn-sbctl",
            "--bare",
            "--columns=_uuid",
            "find",
            "Mac_Binding",
            f'ip="{address}"',
            "logical_port=na-public-router",
            until=lambda result: bool(result.stdout.strip()),
        )

    runner.run("ovn-sbctl", "--all", "destroy", "Mac_Binding")
    for destination in ("172.18.96.101", "172.18.96.102"):
        network("compute-1").wait_for_ping("na-internal1", destination)
        wait_for_binding(destination)
    for destination in ("6812:96::101", "6812:96::102"):
        network("compute-1").wait_for_ping("na-internal1", destination)
        wait_for_binding(destination)

    runner.run("ovn-sbctl", "--all", "destroy", "Mac_Binding")
    for guest, namespace in (
        ("compute-1", "na-external1"),
        ("compute-2", "na-external2"),
    ):
        runner.run(
            "ip",
            "-n",
            namespace,
            "-6",
            "neigh",
            "flush",
            "dev",
            namespace,
            guest=guest,
        )

    for guest, namespace, binding in (
        ("compute-1", "na-external1", "172.18.96.101"),
        ("compute-2", "na-external2", "172.18.96.102"),
    ):
        network(guest).wait_for_ping(namespace, "172.18.96.11")
        wait_for_binding(binding)
    for guest, namespace, binding in (
        ("compute-1", "na-external1", "6812:96::101"),
        ("compute-2", "na-external2", "6812:96::102"),
    ):
        network(guest).wait_for_ping(namespace, "6812:96::11")
        wait_for_binding(binding)
