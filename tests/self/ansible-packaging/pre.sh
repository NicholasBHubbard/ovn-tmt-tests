#!/bin/bash
set -euo pipefail

repo_root=$(cd "$(dirname "$0")/../../.." && pwd)
cd "$repo_root"

test -d roles
test -d playbooks
test -d plans
