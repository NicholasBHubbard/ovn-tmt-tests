import shlex
import subprocess
import sys
import time


class Runner:
    def __init__(
        self,
        topology=None,
        execute=subprocess.run,
        key="/run/ovn-tmt-tests/multihost-driver/id_ed25519",
        sleep=time.sleep,
        user="root",
    ):
        self.topology = topology
        self.execute = execute
        self.key = key
        self.sleep = sleep
        self.user = user

    def run(
        self,
        *command,
        guest=None,
        input=None,
        check=True,
        cwd=None,
        env=None,
    ):
        command = [str(part) for part in command]
        shown = command
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
