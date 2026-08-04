import base64
import json
import os
import subprocess
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

KINDS = ("datapaths", "ports")
STATE_FIELDS = (
    "datapaths",
    "ports",
    "absent_datapaths",
    "absent_ports",
    "started_ns",
)


def _decode(value: Any) -> Any:
    if not isinstance(value, list) or len(value) != 2:
        return value
    kind, contents = value
    if kind == "map":
        return {_decode(key): _decode(item) for key, item in contents}
    if kind == "set":
        return [_decode(item) for item in contents]
    return contents if kind in {"uuid", "named-uuid"} else value


def _rows(command: Sequence[str], table: str, *columns: str) -> list[dict[str, Any]]:
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
    headings = result["headings"]
    rows = result["data"]
    if any(len(row) != len(headings) for row in rows):
        raise ValueError("OVSDB row does not match its headings")
    return [
        {heading: _decode(value) for heading, value in zip(headings, row)}
        for row in rows
    ]


def _expectations(config: dict[str, Any]) -> dict[str, set[str]]:
    result: dict[str, set[str]] = {}
    for kind in KINDS:
        values = config.get(kind, [])
        absent_values = config.get(f"absent_{kind}", [])
        if not isinstance(values, list) or not isinstance(absent_values, list):
            raise ValueError(f"{kind} expectations must be lists")
        if not all(isinstance(item, str) and item for item in values + absent_values):
            raise ValueError(f"{kind} expectations must contain non-empty names")
        wanted = {item for item in values if isinstance(item, str)}
        absent = {item for item in absent_values if isinstance(item, str)}
        if wanted & absent:
            raise ValueError(f"{kind} cannot be both expected and absent")
        result[kind] = wanted
        result[f"absent_{kind}"] = absent
    if not any(result.values()):
        raise ValueError("at least one Southbound expectation is required")
    return result


def verify(expected: dict[str, Any], actual: dict[str, Any]) -> None:
    expectations = _expectations(expected)
    problems = {}
    for kind in KINDS:
        if missing := expectations[kind] - set(actual[kind]):
            problems[f"missing_{kind}"] = sorted(missing)
        if stale := expectations[f"absent_{kind}"] & set(actual[kind]):
            problems[f"stale_{kind}"] = sorted(stale)
    if problems:
        summary = ", ".join(
            f"{name}={values[:10]}{'...' if len(values) > 10 else ''}"
            for name, values in problems.items()
        )
        raise RuntimeError(f"Southbound topology did not converge: {summary}")


def check(config: dict[str, Any]) -> dict[str, Any]:
    timeout = config["timeout"]
    if isinstance(timeout, bool) or not isinstance(timeout, int) or timeout < 1:
        raise ValueError("timeout must be a positive integer")
    for command in ("nbctl", "sbctl"):
        value = config.get(command)
        if (
            isinstance(value, (str, bytes))
            or not isinstance(value, Sequence)
            or not value
            or not all(isinstance(item, str) and item for item in value)
        ):
            raise ValueError(f"{command} must be a non-empty command list")
    _expectations(config)

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


def merge_state(config: dict[str, Any], state: Any) -> dict[str, Any]:
    if not isinstance(state, dict):
        raise ValueError("Southbound state must be an object")
    values = state.get("southbound", state)
    if not isinstance(values, dict):
        raise ValueError("Southbound state fields must be an object")
    return {
        **config,
        **{field: values[field] for field in STATE_FIELDS if field in values},
    }


def main() -> None:
    config = json.loads(
        base64.b64decode(os.environ["OVN_SB_CONVERGENCE_CONFIG"]).decode()
    )
    if not isinstance(config, dict):
        raise ValueError("Southbound convergence configuration must be an object")
    if path := os.environ.get("OVN_SB_CONVERGENCE_STATE_PATH"):
        state = json.loads(Path(path).read_text())
        config = merge_state(config, state)
    print(json.dumps(check(config)))


if __name__ == "__main__":
    main()
