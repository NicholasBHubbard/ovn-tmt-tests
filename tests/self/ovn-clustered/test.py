import os
from pathlib import Path

from ovn_test.command import Runner
from ovn_test.system import ovsdb_control_socket, processes, tcp_listeners


class TestPreconditions:
    def test_services_are_absent(self) -> None:
        runner = Runner()

        assert not processes(runner, "ovn-northd")
        assert not runner.succeeds("ovn-nbctl", "show")
        assert not runner.succeeds("ovn-sbctl", "show")


class TestNorthdConnections:
    def test_both_databases_are_connected(self) -> None:
        runner = Runner()

        for database in ("nb", "sb"):
            assert (
                runner.output(
                    "ovn-appctl",
                    "-t",
                    "ovn-northd",
                    f"{database}-connection-status",
                )
                == "connected"
            )


class TestResult:
    def test_services_and_databases(self) -> None:
        runner = Runner()
        nb_port = int(os.environ.get("OTT_TEST_NB_PORT", "6641"))
        sb_port = int(os.environ.get("OTT_TEST_SB_PORT", "6642"))

        assert processes(runner, "ovsdb-server")
        assert processes(runner, "ovn-northd")
        assert runner.succeeds("ovn-nbctl", "show")
        assert runner.succeeds("ovn-sbctl", "show")
        assert tcp_listeners(runner, nb_port)
        assert tcp_listeners(runner, sb_port)

        if os.environ.get("OTT_TEST_CLUSTER_PROTOCOL", "tcp") == "ssl":
            credentials = (
                "--private-key=/run/ovn-test-pki/private-key.pem",
                "--certificate=/run/ovn-test-pki/certificate.pem",
                "--ca-cert=/run/ovn-test-pki/ca-cert.pem",
            )
            assert runner.succeeds(
                "ovn-nbctl",
                f"--db=ssl:127.0.0.1:{nb_port}",
                *credentials,
                "show",
            )
            assert runner.succeeds(
                "ovn-sbctl",
                f"--db=ssl:127.0.0.1:{sb_port}",
                *credentials,
                "show",
            )

    def test_database_listeners(self) -> None:
        runner = Runner()
        protocol = os.environ.get("OTT_TEST_CLUSTER_PROTOCOL", "tcp")
        listen_address = os.environ.get("OTT_TEST_LISTEN_ADDRESS", "0.0.0.0")
        databases = (
            ("ovnnb_db", os.environ.get("OTT_TEST_NB_PORT", "6641")),
            ("ovnsb_db", os.environ.get("OTT_TEST_SB_PORT", "6642")),
        )

        for daemon, port in databases:
            output = runner.output(
                "ovn-appctl",
                "-t",
                ovsdb_control_socket(runner, daemon),
                "ovsdb-server/list-remotes",
            )
            remotes = output.splitlines()
            assert f"p{protocol}:{port}:{listen_address}" in remotes
            assert not any(remote.startswith("db:") for remote in remotes)

    def test_databases_are_clustered(self) -> None:
        runner = Runner()
        protocol = os.environ.get("OTT_TEST_CLUSTER_PROTOCOL", "tcp")
        members = int(os.environ.get("OTT_TEST_CLUSTER_MEMBERS", "3"))
        databases = (
            (
                "ovnnb_db",
                "OVN_Northbound",
                os.environ.get("OTT_TEST_NB_RAFT_PORT", "6643"),
            ),
            (
                "ovnsb_db",
                "OVN_Southbound",
                os.environ.get("OTT_TEST_SB_RAFT_PORT", "6644"),
            ),
        )

        for daemon, database, port in databases:
            output = runner.output(
                "ovn-appctl",
                "-t",
                ovsdb_control_socket(runner, daemon),
                "cluster/status",
                database,
            )
            assert "Role:" in output
            assert output.count(" at ") == members
            assert f"Address: {protocol}:" in output
            assert f":{port}" in output

    def test_inventory_name_fallback(self, tree: Path, tmp_path: Path) -> None:
        inventory = tmp_path / "inventory.ini"
        inventory.write_text(
            """\
[leader]
leader-node ansible_connection=local

[follower]
follower-node ansible_connection=local
"""
        )

        output = Runner().output(
            "ansible-playbook",
            "-v",
            "-i",
            inventory,
            "playbooks/ovn-clustered.yml",
            "--check",
            "--tags",
            "topology-resolution",
            "-e",
            "ansible_become=false",
            cwd=tree,
        )

        assert (
            '"ovn_central_cluster_members": ["leader-node", "follower-node"]' in output
        )

    def test_ipv6_addresses_are_bracketed(self, tree: Path, tmp_path: Path) -> None:
        inventory = tmp_path / "inventory.ini"
        inventory.write_text(
            """\
[leader]
leader-node ansible_connection=local ovn_central_address=2001:db8::1

[follower]
follower-node ansible_connection=local ovn_central_address=2001:db8::2
"""
        )

        output = Runner().output(
            "ansible-playbook",
            "-v",
            "-i",
            inventory,
            "playbooks/ovn-clustered.yml",
            "--check",
            "--tags",
            "topology-resolution",
            "-e",
            "ansible_become=false",
            cwd=tree,
        )

        assert '"ovn_central_cluster_leader_address": "[2001:db8::1]"' in output
        assert '"tcp:[2001:db8::1]:6641"' in output
        assert '"tcp:[2001:db8::2]:6644"' in output
