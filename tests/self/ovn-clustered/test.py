from ovn_test.command import Runner
from ovn_test.system import ovsdb_control_socket, processes, tcp_listeners


class TestPreconditions:
    def test_services_are_absent(self):
        runner = Runner()

        assert not processes(runner, "ovn-northd")
        assert not runner.succeeds("ovn-nbctl", "show")
        assert not runner.succeeds("ovn-sbctl", "show")


class TestNorthdConnections:
    def test_both_databases_are_connected(self):
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
    def test_services_and_databases(self):
        runner = Runner()

        assert processes(runner, "ovsdb-server")
        assert processes(runner, "ovn-northd")
        assert runner.succeeds("ovn-nbctl", "show")
        assert runner.succeeds("ovn-sbctl", "show")
        assert tcp_listeners(runner, 6641)
        assert tcp_listeners(runner, 6642)

    def test_databases_are_clustered(self):
        runner = Runner()
        databases = (
            ("ovnnb_db", "OVN_Northbound"),
            ("ovnsb_db", "OVN_Southbound"),
        )

        for daemon, database in databases:
            output = runner.output(
                "ovn-appctl",
                "-t",
                ovsdb_control_socket(runner, daemon),
                "cluster/status",
                database,
            )
            assert "Role:" in output

    def test_inventory_name_fallback(self, tree, tmp_path):
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
