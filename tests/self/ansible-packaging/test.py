from pathlib import Path


def contains(path: Path, text: str) -> bool:
    return text in path.read_text()


class TestPreconditions:
    def test_repository_directories_exist(self, tree: Path) -> None:
        for name in ("roles", "playbooks", "plans"):
            assert (tree / name).is_dir()


class TestResult:
    def test_shared_package_role(self, tree: Path) -> None:
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

    def test_ovn_install_package_variables(self, tree: Path) -> None:
        defaults = (tree / "roles/ovn_install/defaults/main.yml").read_text()
        assert "ovn_install_distro_package_names" in defaults
        assert "ovn_install_distro_repository_package_names" in defaults

    def test_ovs_setup_does_not_install_software(self, tree: Path) -> None:
        role = tree / "roles/ovs_setup"
        text = "\n".join(path.read_text() for path in role.rglob("*.yml"))
        for marker in (
            "ovs_setup_install_method",
            "distro_packages",
            "ansible.builtin.git",
            "make install",
        ):
            assert marker not in text

    def test_central_and_chassis_do_not_install_packages(self, tree: Path) -> None:
        for relative, text in (
            ("roles/ovn_central/tasks/main.yml", "distro_packages"),
            ("roles/ovn_central/defaults/main.yml", "ovn_central_package_names"),
            ("roles/ovn_chassis/tasks/main.yml", "distro_packages"),
            ("roles/ovn_chassis/defaults/main.yml", "ovn_chassis_package_names"),
        ):
            assert text not in (tree / relative).read_text()

    def test_entry_playbooks_install_ovn_and_configure_ovs(self, tree: Path) -> None:
        for name in ("ovn-central.yml", "ovn-chassis.yml", "multihost.yml"):
            text = (tree / "playbooks" / name).read_text()
            assert "ovn_install" in text
            assert "ovs_setup" in text

    def test_obsolete_package_setup_is_absent(self, tree: Path) -> None:
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
