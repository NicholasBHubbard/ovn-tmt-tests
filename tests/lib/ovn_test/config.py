import shlex
from pathlib import Path


DEFAULT_DRIVER_RUNTIME_DIR = "/run/ovn-tmt-tests/multihost-driver"


def driver_connection(environment):
    runtime_dir = environment.get("OTT_DRIVER_RUNTIME_DIR", DEFAULT_DRIVER_RUNTIME_DIR)
    return (
        environment.get("OTT_DRIVER_USER", "root"),
        environment.get("OTT_DRIVER_KEY_PATH") or str(Path(runtime_dir) / "id_ed25519"),
    )


def read_int(environment, name, default):
    try:
        return int(environment.get(name, default))
    except (TypeError, ValueError) as error:
        raise ValueError(f"{name} must be an integer") from error


def read_bool(environment, name, default):
    value = str(environment.get(name, default)).lower()
    if value in {"true", "yes", "1"}:
        return True
    if value in {"false", "no", "0"}:
        return False
    raise ValueError(f"{name} must be a boolean")


def read_list(environment, name, default):
    return [value.strip() for value in environment.get(name, default).split(",")]


def database_environment(topology, environment):
    if not read_bool(environment, "OTT_CLUSTERED", False):
        return {}

    members = topology.role("central") + topology.data["roles"].get(
        "central-follower", []
    )
    if not members:
        raise ValueError("clustered OVN requires at least one central guest")

    protocol = "ssl" if read_bool(environment, "OTT_SSL_ENABLED", False) else "tcp"

    def remotes(port):
        return ",".join(
            f"{protocol}:{topology.hostname(member)}:{port}" for member in members
        )

    result = {
        "OVN_NB_DB": remotes(environment.get("OTT_NB_PORT", "6641")),
        "OVN_SB_DB": remotes(environment.get("OTT_SB_PORT", "6642")),
    }
    if protocol == "ssl":
        directory = Path(environment.get("OTT_PKI_REMOTE_DIR", "/run/ovn-test-pki"))
        options = shlex.join(
            [
                f"--private-key={directory / 'private-key.pem'}",
                f"--certificate={directory / 'certificate.pem'}",
                f"--ca-cert={directory / 'ca-cert.pem'}",
            ]
        )
        result["OVN_NBCTL_OPTIONS"] = options
        result["OVN_SBCTL_OPTIONS"] = options
    return result
