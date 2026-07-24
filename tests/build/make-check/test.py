import os

from ovn_test.build import run_make


def test_ovn(runner, source, test_data):
    run_make(
        runner,
        source,
        test_data,
        target=os.environ.get("OTT_MAKE_CHECK_TARGET", "check"),
        testsuiteflags=os.environ.get("OTT_MAKE_CHECK_TESTSUITEFLAGS"),
    )
