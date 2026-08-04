import json
from typing import Optional

import pytest
from ovn_test.command import Runner


@pytest.fixture
def runner() -> Runner:
    return Runner()


def external_id(runner: Runner, name: str) -> Optional[str]:
    output = runner.output(
        "ovs-vsctl",
        "--format=json",
        "--columns=external_ids",
        "list",
        "Open_vSwitch",
        ".",
    )
    pairs = json.loads(output)["data"][0][0][1]
    return dict(pairs).get(name)


class TestPreconditions:
    @pytest.mark.parametrize(
        "name",
        (
            "self-managed",
            "self-delete",
            "self-empty",
            "self-uuid",
            "self-boolean-text",
            "self-special key",
            "self-validation-safety",
        ),
    )
    def test_external_id_is_absent(self, runner: Runner, name: str) -> None:
        assert external_id(runner, name) is None


class TestInitial:
    @pytest.mark.parametrize(
        ("name", "value"),
        (
            ("self-managed", "initial"),
            ("self-delete", "remove-me"),
            ("self-empty", ""),
            ("self-uuid", "01234567-89ab-cdef-0123-456789abcdef"),
            ("self-boolean-text", "true"),
            ("self-special key", 'spaces, commas = and "quotes"'),
            ("self-unmanaged", "preserve"),
        ),
    )
    def test_external_id(self, runner: Runner, name: str, value: str) -> None:
        assert external_id(runner, name) == value


class TestResult:
    @pytest.mark.parametrize(
        ("name", "value"),
        (
            ("self-managed", "updated"),
            ("self-empty", ""),
            ("self-uuid", "01234567-89ab-cdef-0123-456789abcdef"),
            ("self-boolean-text", "true"),
            ("self-unmanaged", "preserve"),
        ),
    )
    def test_preserved_external_id(self, runner: Runner, name: str, value: str) -> None:
        assert external_id(runner, name) == value

    @pytest.mark.parametrize("name", ("self-delete", "self-special key"))
    def test_removed_external_id(self, runner: Runner, name: str) -> None:
        assert external_id(runner, name) is None
