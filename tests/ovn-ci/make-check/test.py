import os
from pathlib import Path

from ovn_test.build import run_make
from ovn_test.command import Runner


def test_ovn(runner: Runner, source: Path, test_data: Path) -> None:
    run_make(
        runner,
        source,
        test_data,
        target=os.environ.get("OTT_MAKE_CHECK_TARGET", "check"),
        testsuiteflags=os.environ.get("OTT_MAKE_CHECK_TESTSUITEFLAGS"),
    )
