import pytest


pytestmark = pytest.mark.usefixtures("setup_scenario")


def test_nat_without_localnet_port(runner, network):
    def restore_localnet():
        runner.run(
            "ovn-nbctl",
            "--may-exist",
            "lsp-add",
            "npl-public",
            "npl-localnet",
            "--",
            "lsp-set-type",
            "npl-localnet",
            "localnet",
            "--",
            "lsp-set-addresses",
            "npl-localnet",
            "unknown",
            "--",
            "lsp-set-options",
            "npl-localnet",
            "network_name=public",
            check=False,
        )

    def assert_traffic():
        for guest, namespace, destination in (
            ("compute-1", "npl-private-a1", "172.30.0.100"),
            ("compute-1", "npl-private-a1", "172.30.0.110"),
            ("compute-1", "npl-private-a1", "172.30.0.120"),
            ("compute-1", "npl-private-a1", "172.30.0.50"),
            ("compute-2", "npl-private-b1", "172.30.0.50"),
            ("compute-1", "npl-public1", "172.30.0.110"),
            ("compute-1", "npl-public1", "172.30.0.120"),
            ("compute-1", "npl-public1", "10.40.0.3"),
            ("compute-1", "npl-public1", "20.40.0.3"),
        ):
            network(guest).wait_for_ping(namespace, destination)

    def wait_for_redirects(expected):
        runner.wait(
            "ovn-sbctl",
            "--bare",
            "--columns=_uuid",
            "find",
            "Port_Binding",
            "logical_port=cr-npl-public-router-port",
            "type=chassisredirect",
            until=lambda result: len(result.stdout.splitlines()) == expected,
        )

    try:
        assert_traffic()

        runner.run(
            "ovn-nbctl",
            "--wait=hv",
            "lsp-set-type",
            "npl-localnet",
            "",
        )
        wait_for_redirects(1)
        assert_traffic()

        runner.run(
            "ovn-nbctl",
            "--wait=hv",
            "lsp-set-type",
            "npl-localnet",
            "localnet",
        )
        wait_for_redirects(0)
        assert_traffic()

        runner.run("ovn-nbctl", "--wait=hv", "lsp-del", "npl-localnet")
        wait_for_redirects(1)
        assert_traffic()
    finally:
        restore_localnet()
