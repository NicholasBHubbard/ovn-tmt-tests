import shutil
from pathlib import Path

import pytest


COMMANDS = (
    "ip",
    "tc",
    "ping",
    "arping",
    "modprobe",
    "ps",
    "tcpdump",
    "ethtool",
    "nft",
    "dhclient",
    "dhcpd",
    "curl",
    "wget",
)


class TestPreconditions:
    def test_dhcpd_is_absent(self):
        assert not shutil.which("dhcpd")


class TestResult:
    @pytest.mark.parametrize("command", COMMANDS)
    def test_command_is_available(self, command):
        assert shutil.which(command)

    def test_fedora_nc_uses_ncat(self):
        if not Path("/etc/fedora-release").exists():
            pytest.skip("not Fedora")

        assert shutil.which("nc")
        assert Path(shutil.which("nc")).resolve() == Path("/usr/bin/ncat")
