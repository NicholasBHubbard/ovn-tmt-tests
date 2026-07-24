from ovn_test.build import run_make


def test_distribution_archive(runner, source, test_data):
    run_make(runner, source, test_data, target="distcheck")

    assert list(source.glob("ovn-*.tar.gz")), (
        f"missing OVN distribution archive in {source}"
    )
