import shutil


def test_ovn_binaries_are_installed(runner):
    binaries = (
        "ovs-vswitchd",
        "ovsdb-server",
        "ovn-nbctl",
        "ovn-sbctl",
        "ovn-northd",
        "ovn-controller",
    )
    for binary in binaries:
        assert shutil.which(binary), f"{binary} is not installed"
        runner.run(binary, "--version")
