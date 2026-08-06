# Test library

`ovn_test` contains reusable Python helpers for OVN tests. It keeps local and
remote command execution, tmt topology handling, OVN and OVS inspection,
network manipulation, and shared scale-test behavior out of individual tests.

Tests import the library normally:

```python
from ovn_test.command import Runner
from ovn_test.network import Network
```

`tests/conftest.py` adds `tests/lib` to the Python import path. Fixtures that
belong to one test family live in that family's `conftest.py`.

## Module Organization

| Module | Responsibility |
| --- | --- |
| `ansible` | Build an inventory from the tmt topology and run Ansible with test-scoped logging. |
| `build` | Run Make targets and preserve Automake testsuite artifacts. |
| `command` | Run, batch, retry, and report local or remote commands. |
| `config` | Parse test configuration and construct SSH and clustered-database settings. |
| `files` | Find text safely in regular UTF-8 files. |
| `load_balancer` | Reconcile owner-scoped OVN load balancers and format VIPs and backends. |
| `namespace` | Manage owner-scoped OVN namespace resources, endpoints, policies, and load balancers. |
| `network` | Inspect Linux network state and manage external test peers. |
| `ovsdb` | Query OVSDB data and decode its JSON representation. |
| `scale` | Verify scale-test environments and manage their shared baseline. |
| `scale_topology` | Generate, reconcile, and clean up configurable OVN scale topologies. |
| `state` | Save and load small test snapshots in tmt data directories. |
| `system` | Inspect processes, listeners, and OVSDB control sockets. |
| `topology` | Validate and query tmt guests, roles, hostnames, and locality. |
| `workload` | Drive measured scale-workload topology and endpoint lifecycles. |

## Boundaries

Put code here when multiple tests need the same behavior or when it represents
a reusable OVN or OVS test primitive. Keep scenario-specific configuration,
setup, and assertions in the test that owns them. Guest provisioning and
persistent system configuration belong in Ansible roles rather than this
library.

Focused module tests live in `tests/self/ovn-test`. Cross-component and
repository contract tests live in `tests/self/contracts`, and integration
self-tests exercise the helpers against real OVN and OVS state. The library
supports Python 3.9 and newer.
