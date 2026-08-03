import base64
import json
import os
import subprocess
from collections.abc import Sequence
from pathlib import Path
from typing import Any


def _decode(value: Any) -> Any:
    if not isinstance(value, list) or len(value) != 2:
        return value
    kind, contents = value
    if kind in {"uuid", "named-uuid"}:
        return contents
    if kind == "set":
        return [_decode(item) for item in contents]
    return value


def _run(*args: object) -> str:
    return subprocess.run(
        ["ovn-nbctl", *map(str, args)],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    ).stdout.strip()


def _rows(table: str, condition: str) -> list[dict[str, Any]]:
    output = _run(
        "--format=json",
        "--data=json",
        "--columns=_uuid,name",
        "find",
        table,
        condition,
    )
    result = json.loads(output)
    headings = result["headings"]
    return [
        {heading: _decode(row[index]) for index, heading in enumerate(headings)}
        for row in result["data"]
    ]


def _validate(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ValueError("load balancer groups must be a list")
    groups = []
    for group in value:
        if not isinstance(group, dict) or set(group) - {
            "id",
            "routers",
            "state",
            "switches",
        }:
            raise ValueError("load balancer group configuration is invalid")
        if not isinstance(group.get("id"), str) or not group["id"]:
            raise ValueError("load balancer group IDs must be non-empty strings")
        if group.get("state", "present") not in {"present", "absent"}:
            raise ValueError("load balancer group states must be present or absent")
        for field in ("switches", "routers"):
            items = group.get(field, [])
            if not isinstance(items, list) or not all(
                isinstance(item, str) and item for item in items
            ):
                raise ValueError(f"load balancer group {field} must be string lists")
        groups.append(group)
    ids = [group["id"] for group in groups]
    if len(ids) != len(set(ids)):
        raise ValueError("load balancer group IDs must be unique")
    return groups


def _transaction(commands: Sequence[Sequence[object]]) -> bool:
    arguments = []
    for command in commands:
        if arguments:
            arguments.append("--")
        arguments.extend(command)
    if not arguments:
        return False
    _run(*arguments)
    return True


def apply(groups: Sequence[dict[str, Any]]) -> bool:
    changed = False
    for group in groups:
        group_id = group["id"]
        matches = _rows("Load_Balancer_Group", f"name={json.dumps(group_id)}")
        if len(matches) > 1:
            raise RuntimeError(f"load balancer group {group_id!r} is not unique")
        if not matches and group.get("state", "present") == "absent":
            continue
        commands = []
        if matches:
            uuid = matches[0]["_uuid"]
            current_switches = {
                row["name"]
                for row in _rows(
                    "Logical_Switch",
                    f"load_balancer_group{{>=}}{uuid}",
                )
            }
            current_routers = {
                row["name"]
                for row in _rows(
                    "Logical_Router",
                    f"load_balancer_group{{>=}}{uuid}",
                )
            }
        else:
            uuid = "@group"
            current_switches = set()
            current_routers = set()
            commands.append(
                [
                    "--id=@group",
                    "create",
                    "Load_Balancer_Group",
                    f"name={json.dumps(group_id)}",
                ]
            )
        present = group.get("state", "present") == "present"
        switches = set(group.get("switches", [])) if present else set()
        routers = set(group.get("routers", [])) if present else set()
        commands += [
            ["remove", "Logical_Switch", item, "load_balancer_group", uuid]
            for item in sorted(current_switches - switches)
        ]
        commands += [
            ["add", "Logical_Switch", item, "load_balancer_group", uuid]
            for item in sorted(switches - current_switches)
        ]
        commands += [
            ["remove", "Logical_Router", item, "load_balancer_group", uuid]
            for item in sorted(current_routers - routers)
        ]
        commands += [
            ["add", "Logical_Router", item, "load_balancer_group", uuid]
            for item in sorted(routers - current_routers)
        ]
        if not present:
            commands.append(["destroy", "Load_Balancer_Group", uuid])
        changed = _transaction(commands) or changed
    return changed


def main() -> None:
    path = os.environ.get("OVN_LOAD_BALANCER_GROUPS_PATH")
    if path:
        data = json.loads(Path(path).read_text())
        groups = (
            data.get("load_balancer_groups", data) if isinstance(data, dict) else data
        )
    else:
        groups = json.loads(base64.b64decode(os.environ["OVN_LOAD_BALANCER_GROUPS"]))
    print("changed" if apply(_validate(groups)) else "unchanged")


if __name__ == "__main__":
    main()
