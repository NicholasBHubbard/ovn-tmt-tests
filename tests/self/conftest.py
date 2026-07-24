import os
from pathlib import Path

import pytest


TREE = Path(os.environ.get("TMT_TREE", Path(__file__).parents[2]))


@pytest.fixture
def tree():
    return TREE


@pytest.fixture
def test_data(tmp_path):
    path = Path(os.environ.get("TMT_TEST_DATA", tmp_path))
    path.mkdir(parents=True, exist_ok=True)
    return path


@pytest.fixture
def snapshots(test_data):
    from ovn_test.state import Snapshots

    return Snapshots.from_environment(
        {
            **os.environ,
            "TMT_TEST_DATA": str(test_data),
        }
    )
