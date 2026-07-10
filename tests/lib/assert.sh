# Shared shell assertions for repository self-tests.
if [ "${TEST_ASSERT_LIB_LOADED:-0}" = 1 ]; then
    return 0
fi
TEST_ASSERT_LIB_LOADED=1

TEST_LIB_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd "$TEST_LIB_DIR/../.." && pwd)
ASSERT_FAILURES=0

cd_repo_root() {
    cd "$REPO_ROOT" || return
}

record_failure() {
    echo "$*"
    ASSERT_FAILURES=1
}

assert_finish() {
    exit "$ASSERT_FAILURES"
}

assert_file() {
    local path=$1

    if [ ! -f "$path" ]; then
        record_failure "Missing expected file: $path"
    fi
}

assert_directory() {
    local path=$1

    if [ ! -d "$path" ]; then
        record_failure "Missing expected directory: $path"
    fi
}

assert_executable() {
    local path=$1

    if [ ! -x "$path" ]; then
        record_failure "Expected executable file: $path"
    fi
}

assert_contains() {
    local path=$1
    local pattern=$2

    if ! grep -R -F -q -- "$pattern" "$path"; then
        record_failure "Expected '$pattern' in $path"
    fi
}

assert_not_contains() {
    local path=$1
    local pattern=$2

    if grep -R -F -q -- "$pattern" "$path"; then
        record_failure "Unexpected '$pattern' in $path"
    fi
}

assert_command_present() {
    local command_name=$1

    if ! command -v "$command_name" >/dev/null 2>&1; then
        record_failure "Expected command in PATH: $command_name"
    fi
}

assert_command_absent() {
    local command_name=$1
    local command_path

    if command_path=$(command -v "$command_name" 2>/dev/null); then
        record_failure "Precondition failed: $command_name is already installed at $command_path"
    fi
}

assert_command_runs() {
    local description=$1
    shift

    if ! "$@" >/dev/null 2>&1; then
        record_failure "Expected command to succeed: $description"
    fi
}

assert_process_present() {
    local process_name=$1

    if ! command -v pgrep >/dev/null 2>&1; then
        record_failure "Cannot check process without pgrep: $process_name"
        return
    fi

    if ! pgrep -a -x "$process_name"; then
        record_failure "Expected process to be running: $process_name"
    fi
}

assert_process_absent() {
    local process_name=$1

    if ! command -v pgrep >/dev/null 2>&1; then
        return
    fi

    if pgrep -a -x "$process_name"; then
        record_failure "Precondition failed: $process_name is already running"
    fi
}

assert_tcp_listening() {
    local port=$1

    if ! command -v ss >/dev/null 2>&1; then
        record_failure "Cannot check listening TCP port without ss: $port"
        return
    fi

    if ! ss -H -ltn "sport = :$port" | grep -q .; then
        record_failure "Expected TCP port to be listening: $port"
    fi
}
