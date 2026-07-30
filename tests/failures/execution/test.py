import pytest


def test_intentional_failure() -> None:
    pytest.fail("Intentional failure during test execution")
