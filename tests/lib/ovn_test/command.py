import json
import os
import shlex
import subprocess
import sys
import time

from ovn_test.config import database_environment, driver_connection


RUN_MANY = """\
import json
import shlex
import subprocess
import sys

label = sys.argv[1]
for command, check in json.load(sys.stdin):
    shown = f"{label}: + {shlex.join(command)}"
    if check:
        print(shown, flush=True)
        subprocess.run(command, check=True, stderr=subprocess.STDOUT)
        continue

    result = subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    if result.returncode:
        shown += f"  [nonfatal {result.returncode}]"
    print(shown, flush=True)
    if result.stdout:
        print(result.stdout, end="", flush=True)
"""


class Runner:
    def __init__(
        self,
        topology=None,
        execute=subprocess.run,
        key=None,
        sleep=time.sleep,
        user=None,
        environment=None,
    ):
        environment = os.environ if environment is None else environment
        configured_user, configured_key = driver_connection(environment)
        self.topology = topology
        self.execute = execute
        self.key = configured_key if key is None else key
        self.sleep = sleep
        self.user = configured_user if user is None else user
        self.database_environment = (
            database_environment(topology, environment) if topology else {}
        )

    def run(
        self,
        *command,
        guest=None,
        input=None,
        check=True,
        cwd=None,
        env=None,
        announce=True,
    ):
        command = [str(part) for part in command]
        shown = command
        if self.database_environment:
            env = {**os.environ, **self.database_environment, **(env or {})}
        if guest is not None and self.topology is None:
            raise ValueError("guest execution requires a tmt topology")
        if guest is not None and not self.topology.is_local(guest):
            remote = shlex.join(command)
            command = [
                "ssh",
                "-i",
                self.key,
                "-o",
                "BatchMode=yes",
                "-o",
                "ConnectTimeout=30",
                "-o",
                "LogLevel=ERROR",
                "-o",
                "StrictHostKeyChecking=no",
                "-o",
                "UserKnownHostsFile=/dev/null",
                f"{self.user}@{self.topology.hostname(guest)}",
                remote,
            ]
            shown = ["ssh", guest, "--", *shown]

        if announce:
            print(f"+ {shlex.join(shown)}", flush=True)
        try:
            result = self.execute(
                command,
                input=input,
                text=True,
                check=check,
                capture_output=True,
                cwd=cwd,
                env=env,
            )
        except subprocess.CalledProcessError as error:
            self._print_output(error)
            raise
        self._print_output(result)
        return result

    def output(self, *command, strip=True, **options):
        output = self.run(*command, **options).stdout
        return output.strip() if strip else output

    def namespace(self, namespace, *command, **options):
        return self.run("ip", "netns", "exec", namespace, *command, **options)

    def run_many(self, commands, guest=None):
        label = guest or "local"
        payload = [
            ([str(part) for part in command], check) for command, check in commands
        ]
        print(f"{label}: command batch started", flush=True)
        try:
            result = self.run(
                "python3",
                "-c",
                RUN_MANY,
                label,
                guest=guest,
                input=json.dumps(payload),
                announce=False,
            )
        except subprocess.CalledProcessError as error:
            print(
                f"{label}: command batch failed (exit status {error.returncode})",
                flush=True,
            )
            raise
        print(f"{label}: command batch completed successfully", flush=True)
        return result

    def succeeds(self, *command, **options):
        try:
            return self.run(*command, check=False, **options).returncode == 0
        except FileNotFoundError:
            return False

    def wait(
        self,
        *command,
        attempts=30,
        interval=1,
        until=None,
        guest=None,
        input=None,
        cwd=None,
        env=None,
    ):
        if attempts < 1:
            raise ValueError("attempts must be a positive integer")

        for attempt in range(attempts):
            result = self.run(
                *command,
                guest=guest,
                input=input,
                check=False,
                cwd=cwd,
                env=env,
            )
            ready = result.returncode == 0 if until is None else until(result)
            if ready:
                return result
            if attempt + 1 < attempts:
                self.sleep(interval)

        shown = shlex.join(str(part) for part in command)
        raise TimeoutError(
            f"{shown} did not satisfy its condition after {attempts} attempts"
        )

    @staticmethod
    def _print_output(result):
        if result.stdout:
            print(result.stdout, end="", flush=True)
        if result.stderr:
            print(result.stderr, end="", file=sys.stderr, flush=True)
