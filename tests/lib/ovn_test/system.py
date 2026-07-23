def processes(runner, name, guest=None):
    result = runner.run("pgrep", "-a", "-x", name, guest=guest, check=False)
    if result.returncode == 1:
        return []
    result.check_returncode()
    return result.stdout.splitlines()


def tcp_listeners(runner, port, guest=None):
    return runner.output(
        "ss",
        "-H",
        "-ltn",
        f"sport = :{port}",
        guest=guest,
    ).splitlines()
