#!/bin/bash
set -euo pipefail

repo_root=$(cd "$(dirname "$0")/../../.." && pwd)
cd "$repo_root"

fail=0

for test_dir in tests/self/*; do
    [ -d "$test_dir" ] || continue

    for path in "$test_dir/main.fmf" "$test_dir/pre.sh" "$test_dir/post.sh"; do
        if [ ! -f "$path" ]; then
            echo "Missing required self-test contract file: $path"
            fail=1
        fi
    done

    for path in "$test_dir/pre.sh" "$test_dir/post.sh"; do
        if [ -f "$path" ] && [ ! -x "$path" ]; then
            echo "Self-test contract script is not executable: $path"
            fail=1
        fi
    done

    if [ -f "$test_dir/main.fmf" ] && ! grep -F -q 'test: ./post.sh' "$test_dir/main.fmf"; then
        echo "Self-test must run post.sh from main.fmf: $test_dir/main.fmf"
        fail=1
    fi

    test_name=${test_dir#tests/self/}
    if ! grep -R -F -q "/tests/self/$test_name" plans/self; then
        echo "Self-test is not referenced by any self-test plan: $test_dir"
        fail=1
    fi

    if ! grep -R -F -q "./tests/self/$test_name/pre.sh" plans/self; then
        echo "Self-test precondition is not referenced by any self-test plan: $test_dir/pre.sh"
        fail=1
    fi
done

if find tests/self -name main.fmf -print0 | xargs -0 grep -F -n -e 'test: ./test.sh' -e 'test: ./verify.sh' -e 'test: ./verify-topology.sh'; then
    echo "Self-tests must run post.sh, not legacy verifier script names."
    fail=1
fi

exit "$fail"
