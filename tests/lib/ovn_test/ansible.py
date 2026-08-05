import os
import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import Callable, Optional, Union

import yaml

from ovn_test.config import driver_connection, read_bool
from ovn_test.topology import Topology


class Ansible:
    def __init__(
        self,
        topology: Topology,
        tree: Union[str, os.PathLike[str]],
        data: Union[str, os.PathLike[str]],
        execute: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
        environment: Optional[Mapping[str, str]] = None,
        key: Optional[str] = None,
        user: Optional[str] = None,
    ) -> None:
        self.topology = topology
        self.tree = Path(tree)
        self.data = Path(data)
        self.execute = execute
        self.environment = os.environ.copy()
        if environment is not None:
            self.environment.update(environment)
        configured_user, configured_key = driver_connection(self.environment)
        self.key = configured_key if key is None else key
        self.user = configured_user if user is None else user

    @classmethod
    def from_environment(
        cls,
        topology: Optional[Topology] = None,
        environment: Optional[Mapping[str, str]] = None,
        execute: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
        key: Optional[str] = None,
        user: Optional[str] = None,
    ) -> "Ansible":
        environment = os.environ if environment is None else environment
        if topology is None:
            topology = Topology.from_file(environment["TMT_TOPOLOGY_YAML"])
        return cls(
            topology,
            tree=environment["TMT_TREE"],
            data=environment["TMT_TEST_DATA"],
            environment=environment,
            execute=execute,
            key=key,
            user=user,
        )

    def inventory(self, path: Optional[Union[str, os.PathLike[str]]] = None) -> Path:
        path = Path(path or self.data / "ansible-inventory.yml")
        path.parent.mkdir(parents=True, exist_ok=True)
        ssh_options = (
            "-o BatchMode=yes -o ConnectTimeout=30 -o LogLevel=ERROR "
            "-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null "
            "-o IdentitiesOnly=yes"
        )
        inventory = {
            "all": {
                "hosts": {
                    guest: {
                        "ansible_host": self.topology.hostname(guest),
                        "ansible_user": self.user,
                        "ansible_ssh_private_key_file": self.key,
                        "ansible_ssh_common_args": ssh_options,
                    }
                    for guest in self.topology.guests()
                },
                "children": {
                    role: {"hosts": {guest: {} for guest in self.topology.role(role)}}
                    for role in self.topology.roles()
                },
            }
        }
        path.write_text(yaml.safe_dump(inventory, sort_keys=False))
        return path

    def run(
        self,
        playbook: Union[str, os.PathLike[str]],
        *arguments: object,
        debug: Optional[bool] = None,
        log: Union[str, os.PathLike[str]] = "setup.log",
    ) -> subprocess.CompletedProcess[str]:
        inventory = self.inventory()
        if debug is None:
            debug = read_bool(self.environment, "OTT_TEST_DEBUG", False)
        verbosity = ["-vvv"] if debug else []
        environment = {
            **self.environment,
            "ANSIBLE_CONFIG": str(self.tree / "ansible.cfg"),
            "ANSIBLE_HOST_KEY_CHECKING": "false",
            "ANSIBLE_ROLES_PATH": str(self.tree / "roles"),
        }

        command = [
            "ansible-playbook",
            *verbosity,
            "-i",
            str(inventory),
            playbook,
            *arguments,
        ]
        result = self.execute(
            command,
            text=True,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            cwd=self.tree,
            env=environment,
        )

        log = Path(log)
        if not log.is_absolute():
            log = self.data / log
        log.parent.mkdir(parents=True, exist_ok=True)
        output = result.stdout or ""
        log.write_text(output)
        print(output, end="", flush=True)

        if result.returncode:
            raise subprocess.CalledProcessError(
                result.returncode,
                result.args,
                output=result.stdout,
                stderr=result.stderr,
            )
        return result
