import re
from typing import Optional

from ovn_test.command import Runner


def processes(runner: Runner, name: str, guest: Optional[str] = None) -> list[str]:
    if not name:
        raise ValueError("process name must not be empty")
    result = runner.run(
        "pgrep", "-a", "-x", "--", re.escape(name), guest=guest, check=False
    )
    if result.returncode == 1:
        return []
    result.check_returncode()
    return result.stdout.splitlines()


def ovsdb_control_socket(
    runner: Runner, database: str, guest: Optional[str] = None
) -> str:
    suffix = f"/{database}.ctl"
    sockets = set()
    for process in processes(runner, "ovsdb-server", guest=guest):
        for argument in process.split():
            if argument.startswith("--unixctl="):
                socket = argument.partition("=")[2]
                if socket.endswith(suffix):
                    sockets.add(socket)
    location = f" on {guest}" if guest else ""
    if not sockets:
        raise LookupError(f"control socket for {database}{location} was not found")
    if len(sockets) > 1:
        raise LookupError(
            f"multiple control sockets for {database}{location} were found: "
            + ", ".join(sorted(sockets))
        )
    return next(iter(sockets))


def tcp_listeners(runner: Runner, port: int, guest: Optional[str] = None) -> list[str]:
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise ValueError("TCP port must be an integer from 1 through 65535")
    return runner.output(
        "ss",
        "-H",
        "-ltn",
        f"sport = :{port}",
        guest=guest,
    ).splitlines()
