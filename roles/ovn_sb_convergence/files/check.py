import base64
import json
import os
import subprocess
import time
from pathlib import Path


def _decode(value):
    if not isinstance(value, list) or len(value) != 2:
        return value
    kind, contents = value
    if kind == "map":
        return {_decode(key): _decode(item) for key, item in contents}
    if kind == "set":
        return [_decode(item) for item in contents]
    return contents if kind in {"uuid", "named-uuid"} else value


def _rows(command, table, *columns):
    output = subprocess.run(
        [
            *command,
            "--format=json",
            "--data=json",
            f"--columns={','.join(columns)}",
            "find",
            table,
        ],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    ).stdout
    result = json.loads(output)
    return [
        {
            heading: _decode(value)
            for heading, value in zip(result["headings"], row, strict=True)
        }
        for row in result["data"]
    ]


def verify(expected, actual):
    problems = {}
    for kind in ("datapaths", "ports"):
        values = expected.get(kind, [])
        absent_values = expected.get(f"absent_{kind}", [])
        if not isinstance(values, list) or not isinstance(absent_values, list):
            raise ValueError(f"{kind} expectations must be lists")
        if not all(isinstance(item, str) and item for item in values + absent_values):
            raise ValueError(f"{kind} expectations must contain non-empty names")
        wanted = set(values)
        absent = set(absent_values)
        if wanted & absent:
            raise ValueError(f"{kind} cannot be both expected and absent")
        if missing := wanted - set(actual[kind]):
            problems[f"missing_{kind}"] = sorted(missing)
        if stale := absent & set(actual[kind]):
            problems[f"stale_{kind}"] = sorted(stale)
    if problems:
        summary = ", ".join(
            f"{name}={values[:10]}{'...' if len(values) > 10 else ''}"
            for name, values in problems.items()
        )
        raise RuntimeError(f"Southbound topology did not converge: {summary}")


def check(config):
    timeout = config["timeout"]
    if isinstance(timeout, bool) or not isinstance(timeout, int) or timeout < 1:
        raise ValueError("timeout must be a positive integer")
    for command in ("nbctl", "sbctl"):
        if not config.get(command) or not all(
            isinstance(item, str) and item for item in config[command]
        ):
            raise ValueError(f"{command} must be a non-empty command list")

    start = config.get("started_ns", time.monotonic_ns())
    if isinstance(start, bool) or not isinstance(start, int):
        raise ValueError("started_ns must be an integer")
    subprocess.run(
        [
            *config["nbctl"],
            "--wait=sb",
            f"--timeout={timeout}",
            "sync",
        ],
        check=True,
    )
    duration = time.monotonic_ns() - start
    if duration < 0:
        raise ValueError("started_ns cannot be in the future")

    datapaths = {
        row["external_ids"].get("name")
        for row in _rows(config["sbctl"], "Datapath_Binding", "external_ids")
    }
    ports = {
        row["logical_port"]
        for row in _rows(config["sbctl"], "Port_Binding", "logical_port")
    }
    actual = {
        "datapaths": datapaths - {None},
        "ports": ports,
    }
    verify(config, actual)
    return {
        "duration_seconds": round(duration / 1_000_000_000, 3),
        "datapaths": len(set(config.get("datapaths", []))),
        "ports": len(set(config.get("ports", []))),
    }


def main():
    config = json.loads(
        base64.b64decode(os.environ["OVN_SB_CONVERGENCE_CONFIG"]).decode()
    )
    if path := os.environ.get("OVN_SB_CONVERGENCE_STATE_PATH"):
        state = json.loads(Path(path).read_text())
        config.update(state.get("southbound", state))
    print(json.dumps(check(config)))


if __name__ == "__main__":
    main()
