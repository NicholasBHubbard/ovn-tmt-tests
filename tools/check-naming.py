#!/usr/bin/env python3
#
# Naming convention:
#   OTT_*                       public configuration owned by ovn-tmt-tests
#   TMT_* / ansible_*           runtime values owned by tmt / Ansible
#   <role_name> or <role_name>_*   variables owned by an Ansible role
# tmt keys such as name, role, how and where are external and remain unchanged.

import sys
from pathlib import Path

import yaml


root = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
errors = []

if not (root / "roles").is_dir():
    sys.exit(f"{root}: roles directory not found")


def load(path):
    with path.open() as source:
        return yaml.safe_load(source) or {}


def environments(data):
    if isinstance(data, dict):
        for key, value in data.items():
            if key in ("environment", "environment+") and isinstance(value, dict):
                yield value
            yield from environments(value)
    elif isinstance(data, list):
        for value in data:
            yield from environments(value)


for directory in ("plans", "tests"):
    for path in (root / directory).glob("**/*.fmf"):
        for environment in environments(load(path)):
            for name in environment:
                if not name.startswith("OTT_"):
                    errors.append(
                        f"{path.relative_to(root)}: {name} must start with OTT_"
                    )

for section in ("defaults", "vars"):
    for path in (root / "roles").glob(f"*/{section}/**/*.y*ml"):
        role = path.relative_to(root / "roles").parts[0]
        for name in load(path):
            if name != role and not name.startswith(f"{role}_"):
                errors.append(
                    f"{path.relative_to(root)}: {name} must be {role} or start with {role}_"
                )

for error in sorted(errors):
    print(error)

raise SystemExit(bool(errors))
