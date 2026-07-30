import shlex
from typing import Optional

from ovn_test.command import Runner


def processes(runner: Runner, name: str, guest: Optional[str] = None) -> list[str]:
    result = runner.run("pgrep", "-a", "-x", name, guest=guest, check=False)
    if result.returncode == 1:
        return []
    result.check_returncode()
    return result.stdout.splitlines()


def ovsdb_control_socket(
    runner: Runner, database: str, guest: Optional[str] = None
) -> str:
    suffix = f"/{database}.ctl"
    for process in processes(runner, "ovsdb-server", guest=guest):
        for argument in shlex.split(process):
            if argument.startswith("--unixctl="):
                socket = argument.partition("=")[2]
                if socket.endswith(suffix):
                    return socket
    raise LookupError(f"control socket for {database} was not found")


def tcp_listeners(runner: Runner, port: int, guest: Optional[str] = None) -> list[str]:
    return runner.output(
        "ss",
        "-H",
        "-ltn",
        f"sport = :{port}",
        guest=guest,
    ).splitlines()
