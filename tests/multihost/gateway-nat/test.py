def test_gateway_nat(topology, network):
    cases = {
        "compute-1": (
            "nat-internal",
            "192.0.2.50",
            "SNAT connectivity to the external endpoint",
        ),
        "gateway-1": (
            "nat-external",
            "192.0.2.100",
            "DNAT connectivity to the internal endpoint",
        ),
    }
    assert topology.current in cases, f"unexpected test guest: {topology.current}"
    namespace, destination, description = cases[topology.current]
    local = network(topology.current)

    assert local.namespace_exists(namespace)
    if topology.current == "gateway-1":
        assert not local.routes(namespace=namespace, destination="default"), (
            "external endpoint must not have a route to the private network"
        )

    try:
        local.wait_for_ping(namespace, destination)
    except TimeoutError:
        raise AssertionError(
            f"no {description} from {namespace} to {destination}"
        ) from None
