#!/bin/bash
set -euo pipefail

source "$TMT_TREE/tests/lib/multihost.sh"

scale_is_boolean() {
    case "$1" in
        true | false | yes | no | 1 | 0) return 0 ;;
        *) return 1 ;;
    esac
}

scale_is_true() {
    case "$1" in
        true | yes | 1) return 0 ;;
        *) return 1 ;;
    esac
}

scale_validate_config() {
    local initial_ports=$1
    local iterations=$2
    local timeout=$3
    local ipv4=$4
    local ipv6=$5
    local chassis_count=$6

    [[ "$initial_ports" =~ ^[1-9][0-9]{0,4}$ ]] || return 1
    [[ "$iterations" =~ ^[1-9][0-9]{0,4}$ ]] || return 1
    [[ "$timeout" =~ ^[1-9][0-9]{0,8}$ ]] || return 1
    [[ "$chassis_count" =~ ^[1-9][0-9]{0,4}$ ]] || return 1
    scale_is_boolean "$ipv4" || return 1
    scale_is_boolean "$ipv6" || return 1
    ((chassis_count >= 2)) || return 1
    ((initial_ports >= chassis_count)) || return 1
    ((iterations >= 1)) || return 1
    ((timeout >= 1)) || return 1
    ((initial_ports + iterations <= 65534)) || return 1
    scale_is_true "$ipv4" || scale_is_true "$ipv6"
}

scale_validate_mtu() {
    local mtu=$1
    local ipv6=$2

    [[ "$mtu" =~ ^[1-9][0-9]{0,4}$ ]] || return 1
    ((mtu >= 576 && mtu <= 65535)) || return 1
    ! scale_is_true "$ipv6" || ((mtu >= 1280))
}

scale_endpoint_name() {
    printf 'dl%05d\n' "$1"
}

scale_host_interface() {
    printf 'dl%05d-p\n' "$1"
}

scale_port_name() {
    printf 'density-light-%05d\n' "$1"
}

scale_mac() {
    local value=$(( $1 + 1 ))

    printf '02:00:%02x:%02x:%02x:%02x\n' \
        $((value >> 24 & 255)) $((value >> 16 & 255)) \
        $((value >> 8 & 255)) $((value & 255))
}

scale_ipv4() {
    local value=$(( $1 + 1 ))

    printf '10.240.%d.%d\n' $((value >> 8 & 255)) $((value & 255))
}

scale_ipv6() {
    printf 'fd00:240::%x\n' "$(( $1 + 1 ))"
}

scale_now_ns() {
    date +%s%N
}

scale_record_metric() {
    local iteration=$1
    local phase=$2
    local start=$3
    local end=$4
    local duration=$((end - start))

    printf '%s,%s,%s\n' "$iteration" "$phase" "$duration" \
        >> "$SCALE_METRICS_FILE"
    printf 'metric iteration=%s phase=%s duration_ns=%s\n' \
        "$iteration" "$phase" "$duration"
}

scale_create_local_endpoint() {
    local guest=$1
    local namespace=$2
    local host_interface=$3
    local port=$4
    local mac=$5
    local ipv4=$6
    local ipv6=$7

    multihost_exec "$guest" bash -s -- \
        "$namespace" "$host_interface" "$port" "$mac" \
        "$ipv4" "$ipv6" "$SCALE_IPV4" "$SCALE_IPV6" \
        "$SCALE_MTU" <<'EOF'
set -euo pipefail
namespace=$1
host_interface=$2
port=$3
mac=$4
ipv4=$5
ipv6=$6
enable_ipv4=$7
enable_ipv6=$8
mtu=$9

ovs-vsctl --if-exists del-port br-int "$host_interface"
ip link delete "$host_interface" 2>/dev/null || true
ip netns delete "$namespace" 2>/dev/null || true
ip netns add "$namespace"
ip link add "$host_interface" type veth peer name "${namespace}-n"
ip link set "${namespace}-n" netns "$namespace"
ip -n "$namespace" link set "${namespace}-n" name eth0
ip link set "$host_interface" mtu "$mtu" up
ip -n "$namespace" link set lo up
ip -n "$namespace" link set eth0 address "$mac" mtu "$mtu" up

case "$enable_ipv4" in
    true | yes | 1) ip -n "$namespace" address replace "$ipv4/16" dev eth0 ;;
esac
case "$enable_ipv6" in
    true | yes | 1)
        ip -n "$namespace" -6 address replace "$ipv6/64" dev eth0 nodad
        ;;
esac

ovs-vsctl --may-exist add-port br-int "$host_interface" \
    -- set Interface "$host_interface" external_ids:iface-id="$port"
EOF
}

scale_wait_for_binding() {
    local port=$1
    local deadline=$((SECONDS + SCALE_TIMEOUT))
    local chassis

    while ((SECONDS < deadline)); do
        chassis=$(ovn-sbctl --bare --columns=chassis \
            find Port_Binding "logical_port=$port" | tr -d '[][:space:]')
        if [ -n "$chassis" ]; then
            return 0
        fi
        sleep 0.2
    done

    echo "Logical port did not bind before timeout: $port" >&2
    ovn-sbctl --columns=logical_port,chassis find Port_Binding \
        "logical_port=$port" >&2 || true
    return 1
}

scale_add_endpoint() {
    local index=$1
    local guest=$2
    local metric_prefix=$3
    local namespace host_interface port mac ipv4 ipv6 addresses
    local start end

    namespace=$(scale_endpoint_name "$index")
    host_interface=$(scale_host_interface "$index")
    port=$(scale_port_name "$index")
    mac=$(scale_mac "$index")
    ipv4=$(scale_ipv4 "$index")
    ipv6=$(scale_ipv6 "$index")
    addresses=$mac
    if scale_is_true "$SCALE_IPV4"; then
        addresses+=" $ipv4"
    fi
    if scale_is_true "$SCALE_IPV6"; then
        addresses+=" $ipv6"
    fi

    SCALE_ENDPOINT_GUESTS[index]=$guest
    SCALE_ENDPOINT_NAMES[index]=$namespace
    SCALE_ENDPOINT_INTERFACES[index]=$host_interface

    start=$(scale_now_ns)
    ovn-nbctl --may-exist lsp-add "$SCALE_SWITCH" "$port" \
        -- lsp-set-addresses "$port" "$addresses"
    end=$(scale_now_ns)
    scale_record_metric "$index" "${metric_prefix}_nb" "$start" "$end"

    start=$(scale_now_ns)
    scale_create_local_endpoint \
        "$guest" "$namespace" "$host_interface" "$port" "$mac" "$ipv4" "$ipv6"
    end=$(scale_now_ns)
    scale_record_metric "$index" "${metric_prefix}_attach" "$start" "$end"

    start=$(scale_now_ns)
    ovn-nbctl --wait=hv --timeout="$SCALE_TIMEOUT" sync
    scale_wait_for_binding "$port"
    end=$(scale_now_ns)
    scale_record_metric "$index" "${metric_prefix}_convergence" "$start" "$end"

}

scale_verify_connectivity() {
    local index=$1
    local source_ordinal=$((index % SCALE_CHASSIS_COUNT))
    local target_ordinal=$(((source_ordinal + 1) % SCALE_CHASSIS_COUNT))
    local source_guest=${SCALE_COMPUTES[$source_ordinal]}
    local target_index=$target_ordinal
    local source_namespace
    local start end

    source_namespace=$(scale_endpoint_name "$index")
    start=$(scale_now_ns)
    if scale_is_true "$SCALE_IPV4"; then
        multihost_wait_for_ping "$source_guest" "$source_namespace" \
            "$(scale_ipv4 "$target_index")" "$SCALE_TIMEOUT"
    fi
    if scale_is_true "$SCALE_IPV6"; then
        multihost_wait_for_ping "$source_guest" "$source_namespace" \
            "$(scale_ipv6 "$target_index")" "$SCALE_TIMEOUT"
    fi
    end=$(scale_now_ns)
    scale_record_metric "$index" connectivity "$start" "$end"
}

scale_cleanup() {
    local start end index guest namespace host_interface
    local status=0

    if [ "${SCALE_CLEANED:-false}" = true ]; then
        return 0
    fi

    start=$(scale_now_ns)
    for index in "${!SCALE_ENDPOINT_GUESTS[@]}"; do
        guest=${SCALE_ENDPOINT_GUESTS[$index]}
        namespace=${SCALE_ENDPOINT_NAMES[$index]}
        host_interface=${SCALE_ENDPOINT_INTERFACES[$index]}
        if ! multihost_exec "$guest" bash -s -- \
            "$namespace" "$host_interface" <<'EOF'
set -euo pipefail
namespace=$1
host_interface=$2
ovs-vsctl --if-exists del-port br-int "$host_interface"
ip link delete "$host_interface" 2>/dev/null || true
ip netns delete "$namespace" 2>/dev/null || true
EOF
        then
            status=1
        fi
    done

    if ! ovn-nbctl --if-exists ls-del "$SCALE_SWITCH"; then
        status=1
    fi
    if ! ovn-nbctl --wait=hv --timeout="$SCALE_TIMEOUT" sync; then
        status=1
    fi
    end=$(scale_now_ns)
    scale_record_metric cleanup cleanup "$start" "$end"
    SCALE_CLEANED=true
    return "$status"
}

scale_verify_cleanup() {
    local index guest namespace host_interface

    if ovn-nbctl --bare --columns=name find Logical_Switch \
        "name=$SCALE_SWITCH" | grep -q .; then
        echo "Scale logical switch remains after cleanup" >&2
        return 1
    fi

    for index in "${!SCALE_ENDPOINT_GUESTS[@]}"; do
        guest=${SCALE_ENDPOINT_GUESTS[$index]}
        namespace=${SCALE_ENDPOINT_NAMES[$index]}
        host_interface=${SCALE_ENDPOINT_INTERFACES[$index]}
        multihost_exec "$guest" bash -c \
            'test ! -e "/var/run/netns/$1" && ! ovs-vsctl port-to-br "$2" >/dev/null 2>&1' \
            _ "$namespace" "$host_interface"
    done
}

scale_main() {
    local index guest start end

    SCALE_INITIAL_PORTS=${OTT_SCALE_INITIAL_PORTS:-2}
    SCALE_ITERATIONS=${OTT_SCALE_ITERATIONS:-3}
    SCALE_TIMEOUT=${OTT_SCALE_TIMEOUT:-60}
    SCALE_IPV4=${OTT_SCALE_IPV4:-true}
    SCALE_IPV6=${OTT_SCALE_IPV6:-true}
    SCALE_MTU=${OTT_SCALE_MTU:-1342}
    SCALE_SWITCH=scale-density-light
    SCALE_METRICS_FILE="${TMT_TEST_DATA:?}/metrics.csv"
    SCALE_CLEANED=false
    declare -g -a SCALE_COMPUTES SCALE_ENDPOINT_GUESTS \
        SCALE_ENDPOINT_NAMES SCALE_ENDPOINT_INTERFACES
    SCALE_ENDPOINT_GUESTS=()
    SCALE_ENDPOINT_NAMES=()
    SCALE_ENDPOINT_INTERFACES=()

    multihost_load_topology
    read -r -a SCALE_COMPUTES <<< "${TMT_ROLES[compute]:-}"
    SCALE_CHASSIS_COUNT=${#SCALE_COMPUTES[@]}
    if ! scale_validate_config "$SCALE_INITIAL_PORTS" "$SCALE_ITERATIONS" \
        "$SCALE_TIMEOUT" "$SCALE_IPV4" "$SCALE_IPV6" \
        "$SCALE_CHASSIS_COUNT"; then
        echo "Invalid OVN scale workload configuration" >&2
        return 2
    fi
    if ! scale_validate_mtu "$SCALE_MTU" "$SCALE_IPV6"; then
        echo "OTT_SCALE_MTU must be 576-65535, or 1280-65535 with IPv6" >&2
        return 2
    fi

    mkdir -p "$TMT_TEST_DATA"
    printf '%s\n' 'iteration,phase,duration_ns' > "$SCALE_METRICS_FILE"
    trap 'scale_cleanup || true' EXIT

    start=$(scale_now_ns)
    ovn-nbctl --may-exist ls-add "$SCALE_SWITCH"
    end=$(scale_now_ns)
    scale_record_metric startup switch "$start" "$end"

    for ((index = 0; index < SCALE_INITIAL_PORTS; index++)); do
        guest=${SCALE_COMPUTES[$((index % SCALE_CHASSIS_COUNT))]}
        scale_add_endpoint "$index" "$guest" startup
    done
    for ((index = 0; index < SCALE_INITIAL_PORTS; index++)); do
        scale_verify_connectivity "$index"
    done

    for ((index = SCALE_INITIAL_PORTS;
          index < SCALE_INITIAL_PORTS + SCALE_ITERATIONS;
          index++)); do
        guest=${SCALE_COMPUTES[$((index % SCALE_CHASSIS_COUNT))]}
        scale_add_endpoint "$index" "$guest" iteration
        scale_verify_connectivity "$index"
    done

    scale_cleanup
    scale_verify_cleanup
    trap - EXIT
    printf 'Scale workload passed with %s initial ports and %s measured iterations across %s chassis.\n' \
        "$SCALE_INITIAL_PORTS" "$SCALE_ITERATIONS" "$SCALE_CHASSIS_COUNT"
    printf 'Metrics: %s\n' "$SCALE_METRICS_FILE"
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    scale_main "$@"
fi
