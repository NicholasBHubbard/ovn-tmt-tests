from copy import deepcopy
from typing import Any

import pytest
from ovn_test.config import (
    database_environment,
    database_remote,
    driver_connection,
    driver_ssh_options,
    read_bool,
    read_int,
    read_list,
    read_port,
)
from ovn_test.topology import Topology


def test_environment_configuration_is_parsed() -> None:
    environment = {
        "COUNT": "7",
        "ENABLED": " YES ",
        "PROTOCOLS": "tcp, udp,sctp",
    }

    assert read_int(environment, "COUNT", 1) == 7
    assert read_bool(environment, "ENABLED", False)
    assert read_list(environment, "PROTOCOLS", "tcp") == ["tcp", "udp", "sctp"]
    assert read_int(environment, "MISSING", 3) == 3
    assert read_list({}, "MISSING", "") == []
    assert read_port(environment, "COUNT", 1) == 7
    assert database_remote("ssl", "2001:db8::1", 6642) == "ssl:[2001:db8::1]:6642"


def test_environment_integer_rejects_invalid_values() -> None:
    with pytest.raises(ValueError, match="COUNT must be an integer"):
        read_int({"COUNT": "many"}, "COUNT", 1)


@pytest.mark.parametrize("value", ("maybe", "", "2"))
def test_environment_boolean_rejects_invalid_values(value: Any) -> None:
    with pytest.raises(ValueError, match="ENABLED must be a boolean"):
        read_bool({"ENABLED": value}, "ENABLED", True)


@pytest.mark.parametrize("value", ("tcp,,udp", "tcp,", ",tcp"))
def test_environment_list_rejects_empty_values(value: str) -> None:
    with pytest.raises(ValueError, match="PROTOCOLS must be a comma-separated list"):
        read_list({"PROTOCOLS": value}, "PROTOCOLS", "tcp")


def test_driver_connection_uses_defaults_and_overrides() -> None:
    assert driver_connection({}) == (
        "root",
        "/run/ovn-tmt-tests/multihost-driver/id_ed25519",
    )
    assert driver_connection(
        {
            "OTT_DRIVER_USER": "tester",
            "OTT_DRIVER_RUNTIME_DIR": "/custom/driver",
        }
    ) == ("tester", "/custom/driver/id_ed25519")
    assert driver_connection({"OTT_DRIVER_KEY_PATH": "/custom/key"}) == (
        "root",
        "/custom/key",
    )


def test_driver_ssh_options_use_configured_timeout() -> None:
    assert "ConnectTimeout=30" in driver_ssh_options({})
    assert "ConnectTimeout=45" in driver_ssh_options(
        {"OTT_DRIVER_CONNECT_TIMEOUT": "45"}
    )
    assert "IdentitiesOnly=yes" in driver_ssh_options({})


@pytest.mark.parametrize(
    ("value", "message"),
    (
        ("invalid", "must be an integer"),
        ("0", "must be a positive integer"),
    ),
)
def test_driver_ssh_options_reject_invalid_timeout(value: str, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        driver_ssh_options({"OTT_DRIVER_CONNECT_TIMEOUT": value})


def clustered_environment(**overrides: str) -> dict[str, str]:
    return {
        "OTT_CLUSTERED": "true",
        "OTT_NB_PORT": "16641",
        "OTT_SB_PORT": "16642",
        **overrides,
    }


def test_database_environment_is_disabled_by_default(topology: Topology) -> None:
    assert database_environment(topology, {}) == {}


@pytest.mark.parametrize("ssl", (False, True))
def test_database_environment_builds_cluster_remotes(
    topology: Topology, ssl: bool
) -> None:
    data = deepcopy(topology.data)
    data["guests"]["central-2"] = {
        "name": "central-2",
        "hostname": "198.51.100.2",
        "role": "central-follower",
    }
    data["roles"]["central-follower"] = ["central", "central-2"]
    protocol = "ssl" if ssl else "tcp"

    result = database_environment(
        Topology(data),
        clustered_environment(
            OTT_SSL_ENABLED=str(ssl).lower(),
            OTT_PKI_REMOTE_DIR="/custom/pki",
        ),
    )

    assert result["OVN_NB_DB"] == (
        f"{protocol}:192.0.2.1:16641,{protocol}:198.51.100.2:16641"
    )
    assert result["OVN_SB_DB"] == (
        f"{protocol}:192.0.2.1:16642,{protocol}:198.51.100.2:16642"
    )
    if ssl:
        expected = (
            "--private-key=/custom/pki/private-key.pem "
            "--certificate=/custom/pki/certificate.pem "
            "--ca-cert=/custom/pki/ca-cert.pem"
        )
        assert result["OVN_NBCTL_OPTIONS"] == expected
        assert result["OVN_SBCTL_OPTIONS"] == expected
    else:
        assert "OVN_NBCTL_OPTIONS" not in result
        assert "OVN_SBCTL_OPTIONS" not in result


def test_database_environment_brackets_ipv6_addresses(topology: Topology) -> None:
    data = deepcopy(topology.data)
    data["guests"]["central"]["hostname"] = "2001:db8::1"
    data["guests"]["central-2"] = {
        "name": "central-2",
        "hostname": "[2001:db8::2]",
        "role": "central-follower",
    }
    data["roles"]["central-follower"] = ["central-2"]

    result = database_environment(Topology(data), clustered_environment())

    assert result["OVN_NB_DB"] == ("tcp:[2001:db8::1]:16641,tcp:[2001:db8::2]:16641")


def test_database_environment_requires_central_guest(topology: Topology) -> None:
    data = deepcopy(topology.data)
    data["roles"] = {"compute": data["roles"]["compute"]}

    with pytest.raises(ValueError, match="requires at least one central guest"):
        database_environment(Topology(data), clustered_environment())


@pytest.mark.parametrize(
    ("name", "value", "message"),
    (
        ("OTT_NB_PORT", "invalid", "OTT_NB_PORT must be an integer"),
        ("OTT_NB_PORT", "0", "OTT_NB_PORT must be between 1 and 65535"),
        ("OTT_SB_PORT", "65536", "OTT_SB_PORT must be between 1 and 65535"),
    ),
)
def test_database_environment_rejects_invalid_ports(
    topology: Topology, name: str, value: str, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        database_environment(topology, clustered_environment(**{name: value}))
