import pytest


pytestmark = pytest.mark.usefixtures("setup_scenario")


def test_provider_traffic_honors_always_tunnel(runner, topology, network):
    compute = network("compute-1")
    compute_2_ip = topology.hostname("compute-2")
    provider_hub_ip = topology.hostname("gateway-1")

    def set_always_tunnel(enabled, check=True):
        if enabled:
            runner.run(
                "ovn-nbctl",
                "set",
                "NB_Global",
                ".",
                "options:always_tunnel=true",
                check=check,
            )
        else:
            runner.run(
                "ovn-nbctl",
                "remove",
                "NB_Global",
                ".",
                "options",
                "always_tunnel",
                check=check,
            )
        runner.run("ovn-nbctl", "--wait=hv", "sync", check=check)

    def assert_paths(tunnel_destination):
        for mac, destination in (
            ("02:00:00:60:10:04", "10.60.0.4"),
            ("02:00:00:60:00:01", "20.60.0.3"),
        ):
            compute.wait_for_ping("at-vm1", destination)
            trace = runner.output(
                "ovs-appctl",
                "ofproto/trace",
                "br-int",
                (
                    "in_port=at-vm1-p,icmp,"
                    "dl_src=02:00:00:60:10:03,"
                    f"dl_dst={mac},nw_src=10.60.0.3,"
                    f"nw_dst={destination},nw_ttl=64,"
                    "icmp_type=8,icmp_code=0"
                ),
                guest="compute-1",
            )
            assert f"dst={tunnel_destination},ttl=" in trace, (
                f"traffic to {destination} did not use tunnel "
                f"destination {tunnel_destination}"
            )

    try:
        set_always_tunnel(False)
        assert_paths(provider_hub_ip)
        set_always_tunnel(True)
        assert_paths(compute_2_ip)
    finally:
        set_always_tunnel(False, check=False)
