import runpy


def test_dpdk_version_line_need_not_be_first(tree):
    workload = runpy.run_path(tree / "tests/build/dpdk/test.py")

    assert workload["supports_dpdk"](
        "ovs-vswitchd (Open vSwitch) 3.6.0\nDPDK 24.11.1\n"
    )
    assert not workload["supports_dpdk"]("ovs-vswitchd (Open vSwitch) 3.6.0\n")
