import shutil

import pytest

from ovn_test.command import Runner


COMMANDS = ("openssl", "pip3", "ps", "tcpdump")
PACKAGES = ("scapy", "pyftpdlib", "tftpy", "netaddr", "pyOpenSSL")


class TestPreconditions:
    def test_scapy_is_absent(self):
        assert not Runner().succeeds("pip3", "show", "scapy")


class TestResult:
    @pytest.mark.parametrize("command", COMMANDS)
    def test_command_is_available(self, command):
        assert shutil.which(command)

    @pytest.mark.parametrize("package", PACKAGES)
    def test_python_package_is_installed(self, package):
        assert Runner().succeeds("pip3", "show", package)
