#!/bin/bash
set -euo pipefail

source "$TMT_TREE/tests/lib/assert.sh"

check_invalid() {
    local invalid_case=$1
    local message=$2
    local output

    output=$(mktemp)
    if ansible-playbook -i localhost, -c local \
        "$TMT_TREE/tests/self/ovn-chassis/invalid-config.yml" \
        -e "ovn_chassis_invalid_case=$invalid_case" > "$output" 2>&1; then
        record_failure "Accepted invalid chassis configuration: $invalid_case"
    elif ! grep -F -q "$message" "$output"; then
        record_failure "Wrong failure for invalid chassis configuration: $invalid_case"
        cat "$output"
    fi
    rm -f "$output"
}

check_invalid duplicate_names \
    "ovn_chassis_instances contains duplicate names."
check_invalid duplicate_containers \
    "Podman chassis container names must be unique."
check_invalid multiple_system \
    "Only one system chassis can use the host OVS database."
check_invalid invalid_runtime \
    "Each chassis needs a valid unique name, runtime and state."

assert_finish
