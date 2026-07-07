---
name: feedback-ci-scope
description: CI only runs self-tests; actual tests (ovn-ci plans) are out of scope for CI and should not be added to the self-test matrix
metadata:
  type: feedback
---

CI should only run self-tests (plans/self/). Actual tests like plans/ovn-ci/ are out of scope for CI and should never be added to the self-test matrix.

**Why:** Self-tests verify that roles and components work mechanically. Actual tests (like running OVN's full make check) are long-running, have external dependencies, and belong in a different execution context — not in the GitHub Actions CI loop.

**How to apply:** Never suggest adding ovn-ci plans to the CI workflow. When creating new actual test plans, they live under plans/ovn-ci/ (or similar) and are run manually or in dedicated infrastructure, not in the self-test CI.
