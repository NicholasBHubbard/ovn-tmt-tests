from pathlib import Path

from ovn_test.build import run_make
from ovn_test.command import Runner


def test_distribution_archive(runner: Runner, source: Path, test_data: Path) -> None:
    run_make(runner, source, test_data, target="distcheck")

    assert list(source.glob("ovn-*.tar.gz")), (
        f"missing OVN distribution archive in {source}"
    )
