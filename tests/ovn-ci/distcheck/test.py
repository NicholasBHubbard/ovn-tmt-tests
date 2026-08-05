from pathlib import Path
from typing import Optional

from ovn_test.build import run_make
from ovn_test.command import Runner


def test_distribution_archive(
    runner: Runner,
    source: Path,
    test_data: Path,
    make_jobs: Optional[int],
) -> None:
    run_make(runner, source, test_data, target="distcheck", jobs=make_jobs)

    assert list(source.glob("ovn-*.tar.gz")), (
        f"missing OVN distribution archive in {source}"
    )
