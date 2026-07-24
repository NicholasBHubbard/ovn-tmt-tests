from ovn_test.command import Runner


class TestFixture:
    def test_makefile_exists(self):
        from pathlib import Path

        assert Path("/tmp/make-check-workspace/Makefile").is_file()


class TestResult:
    def test_role_ran_make(self):
        from pathlib import Path

        assert Path("/tmp/make-check-passed").is_file()

    def test_missing_source_is_rejected(self, tree):
        result = Runner().run(
            "ansible-playbook",
            "-i",
            "localhost,",
            "-c",
            "local",
            "playbooks/make-check.yml",
            "--check",
            "-e",
            "ansible_become=false",
            cwd=tree,
            check=False,
        )

        assert result.returncode
        assert (
            "Set make_check_source_dir to the configured source tree."
            in result.stdout + result.stderr
        )

    def test_ci_configuration(self, tree):
        plans = tree / "plans/ovn-ci"
        main = (plans / "main.fmf").read_text()
        all_plans = "\n".join(path.read_text() for path in plans.glob("*.fmf"))

        assert "playbooks/make-check.yml" not in all_plans
        for expected in (
            "OTT_GIT_REPO: https://github.com/ovn-org/ovn.git",
            "OTT_GIT_VERSION: main",
            "-e ovn_install_git_repo=$OTT_GIT_REPO "
            "-e ovn_install_git_version=$OTT_GIT_VERSION",
            "-e 'ovn_install_configure_flags=$OTT_CONFIGURE_FLAGS'",
            'OTT_MAKE_CHECK_TESTSUITEFLAGS: ""',
            "OTT_SOURCE_DIR: /usr/src/ovn",
            'OTT_MAKE_FLAGS: ""',
            "OTT_DPDK_DIR: /usr/local/dpdk",
            "-e 'ovn_install_source_dir=$OTT_SOURCE_DIR'",
            "-e 'ovn_install_make_flags=$OTT_MAKE_FLAGS'",
            "-e 'ovn_install_dpdk_dir=$OTT_DPDK_DIR'",
        ):
            assert expected in main
        assert (
            "-e 'dpdk_build_install_dir=$OTT_DPDK_DIR'"
            in (plans / "system-dpdk-gcc.fmf").read_text()
        )
        assert all_plans.count('OTT_MAKE_CHECK_TESTSUITEFLAGS: ""') == 1
