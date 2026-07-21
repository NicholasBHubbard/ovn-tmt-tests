#!/bin/bash
set -euo pipefail

source "$TMT_TREE/tests/lib/ovn.sh"

assert_ovn_nb_available
assert_finish
