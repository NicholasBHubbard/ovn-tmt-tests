# Shared command helpers for tests driven from one tmt guest.
if [ "${TEST_MULTIHOST_LIB_LOADED:-0}" = 1 ]; then
    return 0
fi
TEST_MULTIHOST_LIB_LOADED=1

MULTIHOST_DRIVER_KEY=${MULTIHOST_DRIVER_KEY:-/run/ovn-tmt-tests/multihost-driver/id_ed25519}
MULTIHOST_DRIVER_USER=${MULTIHOST_DRIVER_USER:-root}

multihost_debug_enabled() {
    case "${OVN_TEST_DEBUG:-false}" in
        true | yes | 1) return 0 ;;
        *) return 1 ;;
    esac
}

if multihost_debug_enabled; then
    PS4='+ ${BASH_SOURCE##*/}:${LINENO}: '
    set -x
fi

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

multihost_ansible_inventory() {
    local inventory=${1:-"${TMT_TEST_DATA:?}/ansible-inventory.ini"}
    local guest role
    local -a guest_names role_names role_guests

    multihost_load_topology || return
    read -r -a guest_names <<< "$TMT_GUEST_NAMES"
    read -r -a role_names <<< "$TMT_ROLE_NAMES"
    mkdir -p "$(dirname "$inventory")"

    {
        printf '%s\n' '[all]'
        for guest in "${guest_names[@]}"; do
            printf "%s ansible_host=%s ansible_user=%s ansible_ssh_private_key_file=%s ansible_ssh_common_args='%s'\n" \
                "$guest" "${TMT_GUESTS["$guest.hostname"]}" \
                "$MULTIHOST_DRIVER_USER" "$MULTIHOST_DRIVER_KEY" \
                '-o BatchMode=yes -o ConnectTimeout=30 -o LogLevel=ERROR -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null'
        done

        for role in "${role_names[@]}"; do
            printf '\n[%s]\n' "$role"
            read -r -a role_guests <<< "${TMT_ROLES["$role"]}"
            printf '%s\n' "${role_guests[@]}"
        done
    } > "$inventory"

    printf '%s\n' "$inventory"
}

multihost_run_playbook() {
    local playbook=$1
    local inventory setup_log setup_log_prefix guest guest_log status
    local result=0
    local -a verbosity=()
    local -a guest_names guest_logs pids
    shift

    multihost_load_topology || return
    inventory=$(multihost_ansible_inventory) || return
    setup_log=${MULTIHOST_SETUP_LOG:-"${TMT_TEST_DATA:?}/setup.log"}
    setup_log_prefix=${setup_log%.log}
    read -r -a guest_names <<< "$TMT_GUEST_NAMES"
    if multihost_debug_enabled; then
        verbosity=(-vvv)
    fi

    echo "Running test setup: $playbook"
    for guest in "${guest_names[@]}"; do
        guest_log="$setup_log_prefix-$guest.log"
        guest_logs+=("$guest_log")
        (
            ANSIBLE_CONFIG="$TMT_TREE/ansible.cfg" \
            ANSIBLE_HOST_KEY_CHECKING=false \
            ANSIBLE_ROLES_PATH="$TMT_TREE/roles" \
            ansible-playbook "${verbosity[@]}" -i "$inventory" \
                --limit "$guest" "$playbook" "$@"
        ) > "$guest_log" 2>&1 &
        pids+=("$!")
    done

    for pid in "${pids[@]}"; do
        if wait "$pid"; then
            continue
        else
            status=$?
            if [ "$result" -eq 0 ]; then
                result=$status
            fi
        fi
    done

    : > "$setup_log"
    for index in "${!guest_names[@]}"; do
        printf '\n===== %s =====\n' "${guest_names[$index]}" | tee -a "$setup_log"
        tee -a "$setup_log" < "${guest_logs[$index]}"
    done

    return "$result"
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
