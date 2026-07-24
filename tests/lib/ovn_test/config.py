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
