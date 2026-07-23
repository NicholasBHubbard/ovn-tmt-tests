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
