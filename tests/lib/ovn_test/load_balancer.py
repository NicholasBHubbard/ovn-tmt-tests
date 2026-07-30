import json
import subprocess
from collections.abc import Iterable, Mapping, Sequence
from typing import Any, Optional

OPTIONS = {
    "event": "false",
    "hairpin_snat_ip": "169.254.169.5 fd69::5",
    "neighbor_responder": "none",
    "reject": "true",
    "skip_snat": "false",
}


def socket(address: str, port: int, family: int) -> str:
    return f"[{address}]:{port}" if family == 6 else f"{address}:{port}"


def replace(
    runner: Any,
    owner: str,
    name: str,
    protocol: str,
    vips: Optional[Mapping[str, Sequence[str]]] = None,
    switches: Iterable[str] = (),
    routers: Iterable[str] = (),
    group: Optional[str] = None,
) -> subprocess.CompletedProcess[str]:
    command = [
        "ovn-nbctl",
        "--if-exists",
        "lb-del",
        name,
        "--",
        "--id=@lb",
        "create",
        "Load_Balancer",
        f"name={json.dumps(name)}",
        f"protocol={protocol}",
        f"external_ids:ovn-tmt-tests-owner={json.dumps(owner)}",
    ]
    command.extend(
        f"options:{key}={json.dumps(value)}" for key, value in OPTIONS.items()
    )
    command.extend(
        f"vips:{json.dumps(vip)}={json.dumps(','.join(backends))}"
        for vip, backends in (vips or {}).items()
    )
    for table, objects in (
        ("Logical_Switch", switches),
        ("Logical_Router", routers),
    ):
        for item in objects:
            command.extend(["--", "add", table, item, "load_balancer", "@lb"])
    if group:
        command.extend(
            [
                "--",
                "add",
                "Load_Balancer_Group",
                group,
                "load_balancer",
                "@lb",
            ]
        )
    return runner.run(*command)
