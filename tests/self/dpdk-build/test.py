from pathlib import Path


class TestPreconditions:
    def test_install_directory_is_absent(self):
        assert not Path("/usr/local/dpdk").exists()


class TestResult:
    def test_dpdk_is_installed(self):
        root = Path("/usr/local/dpdk")

        assert root.is_dir()
        assert (root / "lib64/pkgconfig/libdpdk.pc").is_file()
