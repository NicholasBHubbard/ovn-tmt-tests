import base64
import json
import os
import subprocess
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import TypedDict, cast


class ConvergenceConfig(TypedDict, total=False):
    timeout: int
    nbctl: list[str]
    sbctl: list[str]
    started_ns: int
    datapaths: list[str]
    ports: list[str]
    absent_datapaths: list[str]
    absent_ports: list[str]


class CheckResult(TypedDict):
    duration_seconds: float
    datapaths: int
    ports: int


def _decode(value: object) -> object:
    if not isinstance(value, list) or len(value) != 2:
        return value
    kind, contents = value
    if not isinstance(kind, str):
        return value
    if kind == "map" and isinstance(contents, list):
        result = {}
        for pair in contents:
            if not isinstance(pair, list) or len(pair) != 2:
                return value
            key, item = pair
            result[_decode(key)] = _decode(item)
        return result
    if kind == "set" and isinstance(contents, list):
        return [_decode(item) for item in contents]
    return contents if kind in {"uuid", "named-uuid"} else value


def _rows(command: Sequence[str], table: str, *columns: str) -> list[dict[str, object]]:
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


def verify(expected: ConvergenceConfig, actual: Mapping[str, set[str]]) -> None:
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


def check(config: ConvergenceConfig) -> CheckResult:
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

    datapaths = set()
    for row in _rows(config["sbctl"], "Datapath_Binding", "external_ids"):
        external_ids = row["external_ids"]
        if isinstance(external_ids, dict):
            name = {str(key): value for key, value in external_ids.items()}.get("name")
            if isinstance(name, str):
                datapaths.add(name)
    ports = {
        str(row["logical_port"])
        for row in _rows(config["sbctl"], "Port_Binding", "logical_port")
    }
    actual = {
        "datapaths": datapaths,
        "ports": ports,
    }
    verify(config, actual)
    return {
        "duration_seconds": round(duration / 1_000_000_000, 3),
        "datapaths": len(set(config.get("datapaths", []))),
        "ports": len(set(config.get("ports", []))),
    }


def main() -> None:
    config = cast(
        ConvergenceConfig,
        json.loads(base64.b64decode(os.environ["OVN_SB_CONVERGENCE_CONFIG"]).decode()),
    )
    if path := os.environ.get("OVN_SB_CONVERGENCE_STATE_PATH"):
        state = json.loads(Path(path).read_text())
        config.update(cast(ConvergenceConfig, state.get("southbound", state)))
    print(json.dumps(check(config)))


if __name__ == "__main__":
    main()
