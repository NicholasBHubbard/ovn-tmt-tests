import os
from pathlib import Path

import pytest

from ovn_test.command import Runner


@pytest.fixture
def runner() -> Runner:
    return Runner()


@pytest.fixture
def source() -> Path:
    return Path(os.environ.get("OTT_SOURCE_DIR", "/usr/src/ovn"))


@pytest.fixture
def test_data() -> Path:
    return Path(os.environ["TMT_TEST_DATA"])
