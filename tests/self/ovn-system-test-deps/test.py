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
    def test_dhcpd_is_absent(self) -> None:
        assert not shutil.which("dhcpd")


class TestResult:
    @pytest.mark.parametrize("command", COMMANDS)
    def test_command_is_available(self, command: str) -> None:
        assert shutil.which(command)

    def test_fedora_nc_uses_ncat(self) -> None:
        if not Path("/etc/fedora-release").exists():
            pytest.skip("not Fedora")

        nc = shutil.which("nc")
        assert nc
        assert Path(nc).resolve() == Path("/usr/bin/ncat")
