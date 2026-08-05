import importlib.util
import subprocess
from pathlib import Path
from types import ModuleType
from typing import Any, Optional

from ovn_test.command import Runner


def load_module(tree: Path, name: str, path: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, tree / path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeRunner(Runner):
    def __init__(self) -> None:
        self.calls = []
        self.batches = []
        self.fail = set()
        self.outputs = {}
        self.returncodes = {}
        self.waits = []

    def run(
        self,
        *command: Any,
        guest: Optional[str] = None,
        input: Any = None,
        check: bool = True,
        cwd: Any = None,
        env: Any = None,
        announce: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        self.calls.append((guest, command, input))
        if command in self.fail:
            raise subprocess.CalledProcessError(1, command)
        stdout = ""
        if command[:3] == ("ovn-nbctl", "create", "Address_Set"):
            stdout = f"uuid-{len(self.calls)}\n"
        if command[:4] == ("ovn-nbctl", "--id=@lb", "create", "Load_Balancer"):
            stdout = f"load-balancer-{len(self.calls)}\n"
        if "Load_Balancer_Group" in command and "--columns=_uuid" in command:
            stdout = "load-balancer-group-uuid\n"
        if "Logical_Switch" in command and command[-1] in {
            'name="switch-0"',
            'name="switch-1"',
        }:
            stdout = "logical-switch-uuid\n"
        if "Port_Binding" in command:
            stdout = "chassis-uuid\n"
        stdout = self.outputs.get((guest, command), stdout)
        return subprocess.CompletedProcess(
            command,
            self.returncodes.get(command, 0),
            stdout,
            "",
        )

    def output(self, *command: Any, **options: Any) -> str:
        return self.run(*command, **options).stdout.strip()

    def namespace(
        self, namespace: str, *command: Any, **options: Any
    ) -> subprocess.CompletedProcess[str]:
        return self.run("ip", "netns", "exec", namespace, *command, **options)

    def run_many(
        self, commands: Any, guest: Optional[str] = None
    ) -> subprocess.CompletedProcess[str]:
        self.batches.append((guest, commands))
        return subprocess.CompletedProcess([], 0, "", "")

    def wait(self, *command: Any, **options: Any) -> subprocess.CompletedProcess[str]:
        self.waits.append((command, options))
        result = self.run(*command, check=False, guest=options.get("guest"))
        condition = options.get("until")
        if condition is not None and not condition(result):
            raise TimeoutError(command)
        return result


def topology_data() -> dict[str, Any]:
    return {
        "guest": {"name": "central", "hostname": "192.0.2.1", "role": "central"},
        "guests": {
            "central": {
                "name": "central",
                "hostname": "192.0.2.1",
                "role": "central",
            },
            "compute-1": {
                "name": "compute-1",
                "hostname": "192.0.2.2",
                "role": "compute",
            },
            "compute-2": {
                "name": "compute-2",
                "hostname": "192.0.2.3",
                "role": "compute",
            },
        },
        "roles": {"central": ["central"], "compute": ["compute-1", "compute-2"]},
    }


def contains(command: Any, *parts: Any) -> bool:
    return any(
        command[index : index + len(parts)] == parts
        for index in range(len(command) - len(parts) + 1)
    )
