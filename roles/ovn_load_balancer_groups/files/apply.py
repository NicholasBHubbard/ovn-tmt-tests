import base64
import json
import os
import subprocess
from pathlib import Path


def _decode(value):
    if not isinstance(value, list) or len(value) != 2:
        return value
    kind, contents = value
    if kind in {"uuid", "named-uuid"}:
        return contents
    if kind == "set":
        return [_decode(item) for item in contents]
    return value


def _run(*args):
    return subprocess.run(
        ["ovn-nbctl", *map(str, args)],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    ).stdout.strip()


def _rows(table, condition):
    output = _run(
        "--format=json",
        "--data=json",
        "--columns=_uuid,name",
        "find",
        table,
        condition,
    )
    result = json.loads(output)
    return [
        {
            heading: _decode(value)
            for heading, value in zip(result["headings"], row, strict=True)
        }
        for row in result["data"]
    ]


def _batch(commands):
    for offset in range(0, len(commands), 100):
        arguments = []
        for command in commands[offset : offset + 100]:
            if arguments:
                arguments.append("--")
            arguments.extend(command)
        if arguments:
            _run(*arguments)


def apply(groups):
    names = [group.get("name", group["id"]) for group in groups]
    if len(names) != len(set(names)):
        raise ValueError("load balancer group names must be unique")
    for group in groups:
        name = group.get("name", group["id"])
        matches = _rows("Load_Balancer_Group", f"name={json.dumps(name)}")
        if len(matches) > 1:
            raise RuntimeError(f"load balancer group {name!r} is not unique")
        if not matches and group.get("state", "present") == "absent":
            continue
        uuid = (
            matches[0]["_uuid"]
            if matches
            else _run("create", "Load_Balancer_Group", f"name={json.dumps(name)}")
        )
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
        present = group.get("state", "present") == "present"
        switches = set(group.get("switches", [])) if present else set()
        routers = set(group.get("routers", [])) if present else set()
        commands = [
            ["remove", "Logical_Switch", item, "load_balancer_group", uuid]
            for item in current_switches - switches
        ]
        commands += [
            ["add", "Logical_Switch", item, "load_balancer_group", uuid]
            for item in switches - current_switches
        ]
        commands += [
            ["remove", "Logical_Router", item, "load_balancer_group", uuid]
            for item in current_routers - routers
        ]
        commands += [
            ["add", "Logical_Router", item, "load_balancer_group", uuid]
            for item in routers - current_routers
        ]
        if present:
            commands.append(
                ["set", "Load_Balancer_Group", uuid, f"name={json.dumps(name)}"]
            )
        else:
            commands.append(["destroy", "Load_Balancer_Group", uuid])
        _batch(commands)


def main():
    path = os.environ.get("OVN_LOAD_BALANCER_GROUPS_PATH")
    if path:
        data = json.loads(Path(path).read_text())
        groups = data.get("load_balancer_groups", data)
    else:
        groups = json.loads(base64.b64decode(os.environ["OVN_LOAD_BALANCER_GROUPS"]))
    apply(groups)


if __name__ == "__main__":
    main()
