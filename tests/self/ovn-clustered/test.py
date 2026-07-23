from ovn_test.command import Runner
from ovn_test.system import processes, tcp_listeners


class TestPreconditions:
    def test_services_are_absent(self):
        runner = Runner()

        assert not processes(runner, "ovn-northd")
        assert not runner.succeeds("ovn-nbctl", "show")
        assert not runner.succeeds("ovn-sbctl", "show")


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
            ("/var/run/ovn/ovnnb_db.ctl", "OVN_Northbound"),
            ("/var/run/ovn/ovnsb_db.ctl", "OVN_Southbound"),
        )

        for control, database in databases:
            output = runner.output(
                "ovn-appctl",
                "-t",
                control,
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
