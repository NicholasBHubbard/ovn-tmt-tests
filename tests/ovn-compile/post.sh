#!/bin/bash
set -euo pipefail

source "$TMT_TREE/tests/lib/ovn.sh"

assert_ovn_binaries_installed
assert_finish
