import os
import shutil
from pathlib import Path

import pytest

from ovn_test.command import Runner


OVN_BINARIES = (
    "ovs-vswitchd",
    "ovsdb-server",
    "ovn-nbctl",
    "ovn-sbctl",
    "ovn-northd",
    "ovn-controller",
)


@pytest.fixture(autouse=True)
def local_sbin(monkeypatch):
    monkeypatch.setenv("PATH", f"/usr/local/sbin:{os.environ['PATH']}")


class TestPreconditions:
    @pytest.mark.parametrize(
        "binary",
        ("ovn-nbctl", "ovn-sbctl", "ovn-northd", "ovn-controller"),
    )
    def test_ovn_binary_is_absent(self, binary):
        assert not shutil.which(binary)


class TestResult:
    @pytest.mark.parametrize("binary", OVN_BINARIES)
    def test_binary_is_installed_and_runnable(self, binary):
        assert shutil.which(binary)
        Runner().run(binary, "--version")

    def test_git_refspec_is_configured(self, tree):
        tasks = (tree / "roles/ovn_install/tasks/git.yml").read_text()

        assert (
            'refspec: "+{{ ovn_install_git_version }}:refs/ovn-tmt/'
            '{{ ovn_install_git_version }}"'
        ) in tasks

    def test_werror_configuration(self):
        if os.environ.get("OTT_EXPECT_WERROR", "false") != "true":
            pytest.skip("Werror was not requested")

        assert "--enable-Werror" in Path("/usr/src/ovn/ovs/config.log").read_text()
        assert "--enable-Werror" in Path("/usr/src/ovn/config.log").read_text()

    def test_dpdk_support(self):
        if os.environ.get("OTT_EXPECT_DPDK", "false") != "true":
            pytest.skip("DPDK was not requested")

        assert "DPDK" in Runner().output("ovs-vswitchd", "--version")
