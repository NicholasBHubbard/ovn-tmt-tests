#!/bin/bash
set -euo pipefail

dnf install -y git

git clone --depth 1 --single-branch --recursive \
    https://github.com/ovn-org/ovn.git /usr/src/ovn
