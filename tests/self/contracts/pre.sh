#!/bin/bash
set -euo pipefail

# Static contract test; no precondition beyond repository checkout availability.
test -d tests/self
