#!/bin/bash
set -euo pipefail

source "$TMT_TREE/tests/lib/multihost.sh"
multihost_run_playbook "$PWD/setup.yml"

server_code='import socket
s=socket.socket()
s.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
s.bind(("0.0.0.0",8080))
s.listen()
while True:
 c,a=s.accept()
 c.sendall(REPLY)
 c.close()'

stop_backend() {
    local guest=$1
    local namespace=$2

    multihost_exec "$guest" bash -c \
        "test ! -f /tmp/$namespace.pid || kill \$(cat /tmp/$namespace.pid) 2>/dev/null || true"
}

cleanup() {
    stop_backend compute-1 lb-backend-a
    stop_backend compute-2 lb-backend-b
}
trap cleanup EXIT

backend_server() {
    local guest=$1
    local namespace=$2
    local reply=$3
    local code encoded

    printf -v code 'REPLY=b"%s\\n"\n%s' "$reply" "$server_code"
    encoded=$(printf '%s' "$code" | base64 -w 0)

    multihost_exec "$guest" bash -c \
        "printf %s $encoded | base64 -d >/tmp/$namespace-server.py; ip netns exec $namespace nohup python3 /tmp/$namespace-server.py </dev/null >/tmp/$namespace.log 2>&1 & echo \$! >/tmp/$namespace.pid"
}

backend_server compute-1 lb-backend-a backend-a
backend_server compute-2 lb-backend-b backend-b
sleep 1

client_code='import socket
s=socket.create_connection(("172.31.1.100",8080),3)
print(s.recv(64).decode().strip())'
responses=""
for _ in {1..30}; do
    responses+="$(multihost_ns_exec compute-1 lb-external \
        python3 -c "$client_code")"$'\n'
done

for backend in backend-a backend-b; do
    if ! grep -qx "$backend" <<< "$responses"; then
        echo "Load balancer did not reach $backend" >&2
        echo "$responses" >&2
        exit 1
    fi
done
