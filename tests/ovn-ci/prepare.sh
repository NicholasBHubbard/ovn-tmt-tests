#!/bin/bash
set -euo pipefail

git clone "${OVN_REPO}" /workspace/ovn \
    --branch "${OVN_BRANCH}" --single-branch --depth 1

cd /workspace/ovn
git submodule update --init --single-branch --depth 1
