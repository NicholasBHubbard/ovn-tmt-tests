def contains(path, text):
    return text in path.read_text()


class TestPreconditions:
    def test_repository_directories_exist(self, tree):
        for name in ("roles", "playbooks", "plans"):
            assert (tree / name).is_dir()


class TestResult:
    def test_shared_package_role(self, tree):
        defaults = tree / "roles/distro_packages/defaults/main.yml"
        tasks = tree / "roles/distro_packages/tasks/main.yml"

        assert defaults.is_file()
        assert tasks.is_file()
        assert contains(tasks, "distro_packages_names")
        assert contains(tasks, 'ansible_facts["pkg_mgr"] == "apt"')
        assert contains(
            tasks,
            'ansible_facts["pkg_mgr"] in ["apt", "dnf", "dnf5", "yum", "homebrew"]',
        )

    def test_role_package_variables(self, tree):
        expected = {
            "roles/ovn_install/defaults/main.yml": (
                "ovn_install_distro_package_names",
                "ovn_install_distro_repository_package_names",
            ),
            "roles/ovs_setup/defaults/main.yml": (
                "ovs_setup_package_names",
                "ovs_setup_repository_package_names",
            ),
        }
        for relative, names in expected.items():
            text = (tree / relative).read_text()
            for name in names:
                assert name in text

    def test_central_and_chassis_do_not_install_packages(self, tree):
        for relative, text in (
            ("roles/ovn_central/tasks/main.yml", "distro_packages"),
            ("roles/ovn_central/defaults/main.yml", "ovn_central_package_names"),
            ("roles/ovn_chassis/tasks/main.yml", "distro_packages"),
            ("roles/ovn_chassis/defaults/main.yml", "ovn_chassis_package_names"),
        ):
            assert text not in (tree / relative).read_text()

    def test_entry_playbooks_install_ovn_and_ovs(self, tree):
        for name in ("ovn-central.yml", "ovn-chassis.yml", "multihost.yml"):
            text = (tree / "playbooks" / name).read_text()
            assert "ovn_install" in text
            assert "ovs_setup" in text

    def test_obsolete_package_setup_is_absent(self, tree):
        for root in ("playbooks", "roles"):
            text = "\n".join(
                path.read_text(errors="replace")
                for path in (tree / root).rglob("*")
                if path.is_file()
            )
            assert "centos-release-nfv-openvswitch" not in text
            assert "Enable NFV SIG repo" not in text

        plans = "\n".join(
            path.read_text(errors="replace")
            for path in (tree / "plans").rglob("*")
            if path.is_file()
        )
        assert "dnf install -y openvswitch" not in plans
