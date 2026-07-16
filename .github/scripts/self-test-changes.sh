#!/bin/bash
set -euo pipefail

while IFS= read -r path; do
    case "$path" in
        README.md|Unified-OVN-Test-System-Proposal.md|LICENSE|LICENSE.*|COPYING|COPYING.*|.gitignore|docs/*)
            ;;
        *)
            echo true
            exit 0
            ;;
    esac
done

echo false
