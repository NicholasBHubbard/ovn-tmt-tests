# Test library

`ovn_test` contains reusable Python helpers for OVN tests. It keeps command
execution, topology access, network manipulation, and shared workload logic out
of individual test files.

Tests import the library normally:

```python
from ovn_test.command import Runner
from ovn_test.network import Network
```

`tests/conftest.py` adds `tests/lib` to the Python import path. Some test
families also load fixtures from `ovn_test.pytest_build` or
`ovn_test.pytest_multihost` through their own `conftest.py`.

## Module Organization

- `command`, `topology`, `ansible`, `ovsdb`, and `config` provide helpers for
  running commands, finding test guests by name or role, obtaining their
  addresses, invoking Ansible, querying OVN databases, and reading test
  configuration.
- `network`, `namespace`, and `load_balancer` provide reusable networking
  primitives.
- `build`, `files`, `system`, and `state` provide focused build, filesystem,
  system-inspection, and result-state helpers.
- `scale_topology`, `scale`, and `workload` implement shared OVN scale-test
  topology and workload behavior. `_scale_topology_apply` is an internal
  implementation module.
- `pytest_build` and `pytest_multihost` provide fixtures for their respective
  test families.

## Boundaries

Put code here when multiple tests need the same behavior or when it represents
a reusable test primitive. Keep scenario-specific setup and assertions in the
test that owns them. Guest provisioning and persistent system configuration
belong in Ansible roles rather than this library.

Focused library tests live in `tests/self/ovn-test`. Integration self-tests
also exercise the helpers against real OVN and OVS state. The library is
formatted and linted with Ruff and type-checked with ty in CI.
