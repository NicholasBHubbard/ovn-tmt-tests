import os
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from ovn_test.config import driver_connection, read_bool
from ovn_test.topology import Topology


class Ansible:
    def __init__(
        self,
        topology,
        tree,
        data,
        execute=subprocess.run,
        environment=None,
        key=None,
        user=None,
    ):
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
        topology=None,
        environment=None,
        **options,
    ):
        environment = os.environ if environment is None else environment
        if topology is None:
            topology = Topology.from_file(environment["TMT_TOPOLOGY_YAML"])
        return cls(
            topology,
            tree=environment["TMT_TREE"],
            data=environment["TMT_TEST_DATA"],
            environment=environment,
            **options,
        )

    def inventory(self, path=None):
        path = Path(path or self.data / "ansible-inventory.ini")
        path.parent.mkdir(parents=True, exist_ok=True)
        ssh_options = (
            "-o BatchMode=yes -o ConnectTimeout=30 -o LogLevel=ERROR "
            "-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null"
        )
        lines = ["[all]"]
        for guest in self.topology.guests():
            lines.append(
                f"{guest} ansible_host={self.topology.hostname(guest)} "
                f"ansible_user={self.user} "
                f"ansible_ssh_private_key_file={self.key} "
                f"ansible_ssh_common_args='{ssh_options}'"
            )
        for role in self.topology.roles():
            lines.extend(("", f"[{role}]", *self.topology.role(role)))
        path.write_text("\n".join(lines) + "\n")
        return path

    def run(self, playbook, *arguments, debug=None, log="setup.log"):
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

        def run_guest(guest):
            command = [
                "ansible-playbook",
                *verbosity,
                "-i",
                str(inventory),
                "--limit",
                guest,
                playbook,
                *arguments,
            ]
            return self.execute(
                command,
                text=True,
                check=False,
                capture_output=True,
                cwd=self.tree,
                env=environment,
            )

        guests = self.topology.guests()
        with ThreadPoolExecutor(max_workers=len(guests)) as executor:
            results = dict(zip(guests, executor.map(run_guest, guests)))

        log = Path(log)
        if not log.is_absolute():
            log = self.data / log
        log.parent.mkdir(parents=True, exist_ok=True)
        combined = []
        for guest, result in results.items():
            output = (result.stdout or "") + (result.stderr or "")
            log.with_name(f"{log.stem}-{guest}{log.suffix}").write_text(output)
            combined.append(f"\n===== {guest} =====\n{output}")
        log.write_text("".join(combined))
        print(log.read_text(), end="", flush=True)

        for result in results.values():
            if result.returncode:
                raise subprocess.CalledProcessError(
                    result.returncode,
                    result.args,
                    output=result.stdout,
                    stderr=result.stderr,
                )
        return results
