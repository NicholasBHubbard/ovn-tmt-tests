import pytest


pytestmark = pytest.mark.usefixtures("setup_scenario")

SERVER = """\
import socket
import sys

server = socket.socket()
server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
server.bind(("0.0.0.0", 8080))
server.listen()
while True:
    client, _ = server.accept()
    client.sendall((sys.argv[1] + "\\n").encode())
    client.close()
"""

CLIENT = """\
import socket

client = socket.create_connection(("172.31.1.100", 8080), 3)
print(client.recv(64).decode().strip())
"""


def test_load_balancing_across_chassis(runner):
    backends = (
        ("compute-1", "lb-backend-a", "backend-a", "ott-lb-backend-a"),
        ("compute-2", "lb-backend-b", "backend-b", "ott-lb-backend-b"),
    )

    def stop_backends():
        for guest, _, _, unit in backends:
            runner.run("systemctl", "stop", unit, guest=guest, check=False)
            runner.run("systemctl", "reset-failed", unit, guest=guest, check=False)

    stop_backends()
    try:
        for guest, namespace, reply, unit in backends:
            runner.run(
                "systemd-run",
                "--quiet",
                f"--unit={unit}",
                "--collect",
                f"--property=NetworkNamespacePath=/run/netns/{namespace}",
                "python3",
                "-c",
                SERVER,
                reply,
                guest=guest,
            )
            runner.wait("systemctl", "is-active", "--quiet", unit, guest=guest)

        responses = [
            runner.output(
                "ip",
                "netns",
                "exec",
                "lb-external",
                "python3",
                "-c",
                CLIENT,
                guest="compute-1",
            )
            for _ in range(30)
        ]
        for backend in ("backend-a", "backend-b"):
            assert backend in responses, f"load balancer did not reach {backend}"
    finally:
        stop_backends()
