import json
import os

import pytest


pytestmark = pytest.mark.usefixtures("setup_scenario")

UDP_PROBE = """\
import socket

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.sendto(bytes(1024), ("10.70.0.1", 8080))
"""


def test_path_mtu_across_encapsulation(runner, topology, network):
    encapsulation = os.environ.get("OTT_TEST_ENCAP", "geneve")
    settings = {
        "geneve": ("genev_sys_6081", 942),
        "vxlan": ("vxlan_sys_4789", 950),
    }
    assert encapsulation in settings, f"unsupported encapsulation: {encapsulation}"
    system_interface, expected_mtu = settings[encapsulation]
    compute_2_ip = topology.hostname("compute-2")
    route = json.loads(
        runner.output(
            "ip",
            "-j",
            "-4",
            "route",
            "get",
            compute_2_ip,
            guest="compute-1",
        )
    )[0]

    def replace_underlay_mtu(mtu):
        command = ["ip", "route", "replace", f"{compute_2_ip}/32"]
        if route.get("gateway"):
            command.extend(("via", route["gateway"]))
        command.extend(("dev", route["dev"], "mtu", mtu))
        runner.run(*command, guest="compute-1")

    def reset_endpoint_routes():
        runner.namespace(
            "pmtu-vm1",
            "ip",
            "route",
            "flush",
            "dev",
            "pmtu-vm1",
            guest="compute-1",
        )
        runner.namespace(
            "pmtu-vm1",
            "ip",
            "route",
            "add",
            "10.70.0.0/24",
            "dev",
            "pmtu-vm1",
            guest="compute-1",
        )
        runner.namespace(
            "pmtu-vm1",
            "ip",
            "route",
            "add",
            "default",
            "via",
            "10.70.0.1",
            "dev",
            "pmtu-vm1",
            guest="compute-1",
        )

    def set_encapsulation(value, check=True):
        for guest in ("compute-1", "compute-2", "gateway-1"):
            runner.run(
                "ovs-vsctl",
                "set",
                "open",
                ".",
                f"external-ids:ovn-encap-type={value}",
                guest=guest,
                check=check,
            )

    def oversized_ping(destination):
        return runner.namespace(
            "pmtu-vm1",
            "ping",
            "-c",
            "5",
            "-s",
            "1300",
            "-M",
            "do",
            destination,
            guest="compute-1",
            check=False,
        )

    try:
        set_encapsulation(encapsulation)
        for guest in ("compute-1", "compute-2"):
            runner.wait(
                "ip",
                "link",
                "show",
                system_interface,
                guest=guest,
            )

        reset_endpoint_routes()
        network("compute-1").wait_for_ping("pmtu-vm1", "10.70.0.4")
        replace_underlay_mtu(1200)
        result = oversized_ping("10.70.0.4")
        assert "message too long" in (result.stdout + result.stderr).lower()

        reset_endpoint_routes()
        network("compute-1").wait_for_ping("pmtu-vm1", "20.70.0.3")
        replace_underlay_mtu(1100)
        result = oversized_ping("20.70.0.3")
        assert "message too long" in (result.stdout + result.stderr).lower()

        reset_endpoint_routes()
        replace_underlay_mtu(1000)
        for _ in range(30):
            runner.namespace(
                "pmtu-vm1",
                "python3",
                "-c",
                UDP_PROBE,
                guest="compute-1",
                check=False,
            )
        learned = runner.output(
            "ip",
            "netns",
            "exec",
            "pmtu-vm1",
            "ip",
            "route",
            "get",
            "10.70.0.1",
            "dev",
            "pmtu-vm1",
            guest="compute-1",
        )
        assert f"mtu {expected_mtu}" in learned
    finally:
        runner.run(
            "ip",
            "route",
            "del",
            f"{compute_2_ip}/32",
            guest="compute-1",
            check=False,
        )
        set_encapsulation("geneve", check=False)
