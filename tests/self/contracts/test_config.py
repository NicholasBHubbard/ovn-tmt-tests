from typing import Any

import pytest
from ovn_test.config import read_bool, read_int, read_list


def test_environment_configuration_is_parsed() -> None:
    environment = {
        "COUNT": "7",
        "ENABLED": "yes",
        "PROTOCOLS": "tcp, udp,sctp",
    }

    assert read_int(environment, "COUNT", 1) == 7
    assert read_bool(environment, "ENABLED", False)
    assert read_list(environment, "PROTOCOLS", "tcp") == ["tcp", "udp", "sctp"]
    assert read_int(environment, "MISSING", 3) == 3


def test_environment_integer_rejects_invalid_values() -> None:
    with pytest.raises(ValueError, match="COUNT must be an integer"):
        read_int({"COUNT": "many"}, "COUNT", 1)


@pytest.mark.parametrize("value", ("maybe", "", "2"))
def test_environment_boolean_rejects_invalid_values(value: Any) -> None:
    with pytest.raises(ValueError, match="ENABLED must be a boolean"):
        read_bool({"ENABLED": value}, "ENABLED", True)
