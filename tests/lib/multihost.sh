# Shared command helpers for tests driven from one tmt guest.
if [ "${TEST_MULTIHOST_LIB_LOADED:-0}" = 1 ]; then
    return 0
fi
TEST_MULTIHOST_LIB_LOADED=1

MULTIHOST_DRIVER_KEY=${MULTIHOST_DRIVER_KEY:-/run/ovn-tmt-tests/multihost-driver/id_ed25519}
MULTIHOST_DRIVER_USER=${MULTIHOST_DRIVER_USER:-root}

multihost_load_topology() {
    if ! declare -p TMT_GUESTS >/dev/null 2>&1; then
        if [ -z "${TMT_TOPOLOGY_BASH:-}" ] || [ ! -f "$TMT_TOPOLOGY_BASH" ]; then
            echo "TMT guest topology is unavailable" >&2
            return 2
        fi

        # tmt creates this file at runtime. Its declarations must be global
        # because this lazy loader runs inside a function.
        # shellcheck disable=SC1090
        source <(sed 's/^declare -A /declare -gA /' "$TMT_TOPOLOGY_BASH")
    fi
}

multihost_guest_hostname() {
    local guest=$1
    local key="${guest}.hostname"

    multihost_load_topology || return

    if [ -z "${TMT_GUESTS["$key"]:-}" ]; then
        echo "Unknown tmt guest: $guest" >&2
        return 2
    fi

    printf '%s\n' "${TMT_GUESTS["$key"]}"
}

multihost_exec() {
    local guest=$1
    local hostname
    local remote_command
    shift

    if [ "$#" -eq 0 ]; then
        echo "multihost_exec requires a command" >&2
        return 2
    fi

    multihost_load_topology || return
    hostname=$(multihost_guest_hostname "$guest") || return

    if [ "${TMT_GUEST["name"]:-}" = "$guest" ]; then
        "$@"
        return
    fi

    printf -v remote_command '%q ' "$@"
    ssh -i "$MULTIHOST_DRIVER_KEY" \
        -o BatchMode=yes \
        -o ConnectTimeout=30 \
        -o LogLevel=ERROR \
        -o StrictHostKeyChecking=no \
        -o UserKnownHostsFile=/dev/null \
        "${MULTIHOST_DRIVER_USER}@${hostname}" \
        "$remote_command"
}

multihost_ns_exec() {
    local guest=$1
    local namespace=$2
    shift 2

    multihost_exec "$guest" ip netns exec "$namespace" "$@"
}

multihost_wait_for_ping() {
    local guest=$1
    local namespace=$2
    local destination=$3
    local attempts=${4:-30}

    while [ "$attempts" -gt 0 ]; do
        if multihost_ns_exec "$guest" "$namespace" \
            ping -q -c 1 -W 1 "$destination"; then
            return 0
        fi
        attempts=$((attempts - 1))
        [ "$attempts" -eq 0 ] || sleep 1
    done

    echo "No connectivity from $guest/$namespace to $destination" >&2
    return 1
}

multihost_expect_no_ping() {
    local guest=$1
    local namespace=$2
    local destination=$3

    if multihost_ns_exec "$guest" "$namespace" \
        ping -q -c 2 -W 1 "$destination"; then
        echo "Unexpected connectivity from $guest/$namespace to $destination" >&2
        return 1
    fi
}
