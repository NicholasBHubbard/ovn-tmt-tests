from pathlib import Path

from ovn_test.scale import ScaleBaseline

from ._support import FakeRunner, contains


def test_scale_baseline_reuses_worker_topology(tmp_path: Path) -> None:
    runner = FakeRunner()
    topology = {
        "physical_bridge": "br-provider",
        "load_balancer_group": "cluster-lb-group",
        "workers": [
            {
                "name": "worker-0",
                "chassis": "compute-1",
                "switch": "switch-0",
                "gateway_router": "gwrouter-worker-0",
                "internal": {
                    "ipv4": "10.0.0.0/24",
                    "ipv6": "fd10::/80",
                },
                "external": {
                    "ipv4": "172.16.0.0/24",
                    "ipv6": "fd20::/80",
                },
            },
            {
                "name": "worker-1",
                "chassis": "compute-2",
                "switch": "switch-1",
                "gateway_router": "gwrouter-worker-1",
                "internal": {
                    "ipv4": "10.0.1.0/24",
                    "ipv6": "fd10:0:0:1::/80",
                },
                "external": {
                    "ipv4": "172.16.1.0/24",
                    "ipv6": "fd20:0:0:1::/80",
                },
            },
        ],
    }
    baseline = ScaleBaseline(
        runner,
        ["compute-1", "compute-2"],
        topology,
        tmp_path,
        pods_per_worker=1,
        protocols=["tcp"],
        ipv4=True,
        ipv6=False,
        mtu=1400,
        timeout=3,
        sync_timeout=10,
        name="scale-base",
        prefix="sb",
    )

    baseline.create()

    assert len(baseline.workload.endpoints) == 2
    assert set(baseline.external.peers) == {"worker-0", "worker-1"}
    assert ("ovn-nbctl", "--wait=hv", "--timeout=10", "sync") in [
        call[1] for call in runner.calls
    ]
    load_balancers = [
        command
        for _, command, _ in runner.calls
        if contains(command, "create", "Load_Balancer")
    ]
    assert len(load_balancers) == 3
    cluster = next(
        command for command in load_balancers if 'name="lb-cluster1-tcp"' in command
    )
    assert len([argument for argument in cluster if argument.startswith("vips:")]) == 65
    assert (
        'vips:"4.0.0.1:80"="6.0.0.1:8080,6.0.0.2:8080,10.0.0.1:8080,10.0.1.1:8080"'
    ) in cluster
    assert contains(
        cluster,
        "add",
        "Logical_Router",
        "gwrouter-worker-1",
        "load_balancer",
        "@lb",
    )
    gateway = next(
        command
        for command in load_balancers
        if 'name="lb-gwrouter-worker-0-tcp"' in command
    )
    assert not [argument for argument in gateway if argument.startswith("vips:")]

    baseline.cleanup()
    assert baseline.workload.cleaned
