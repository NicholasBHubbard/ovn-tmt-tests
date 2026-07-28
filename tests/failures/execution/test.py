import pytest


def test_intentional_failure():
    pytest.fail("Intentional failure during test execution")
