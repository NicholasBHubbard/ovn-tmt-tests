import shlex


def processes(runner, name, guest=None):
    result = runner.run("pgrep", "-a", "-x", name, guest=guest, check=False)
    if result.returncode == 1:
        return []
    result.check_returncode()
    return result.stdout.splitlines()


def ovsdb_control_socket(runner, database, guest=None):
    suffix = f"/{database}.ctl"
    for process in processes(runner, "ovsdb-server", guest=guest):
        for argument in shlex.split(process):
            if argument.startswith("--unixctl="):
                socket = argument.partition("=")[2]
                if socket.endswith(suffix):
                    return socket
    raise LookupError(f"control socket for {database} was not found")


def tcp_listeners(runner, port, guest=None):
    return runner.output(
        "ss",
        "-H",
        "-ltn",
        f"sport = :{port}",
        guest=guest,
    ).splitlines()
