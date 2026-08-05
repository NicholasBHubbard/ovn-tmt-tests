# run_diagnostics

## Purpose

Collect best-effort guest diagnostics around a test workload. The `start`
action records when the workload began. The `collect` action then captures the
system journal from that point, current system state, and tails of configured
OVN and OVS logs.

Collection produces a gzip-compressed tar archive named after the inventory
host. Diagnostic failures do not fail the Ansible run, so a missing archive or
incomplete contents do not hide the workload's actual result. Failures are
reported in the Ansible output, and command errors are preserved with the
collected data.

## Configuration

`run_diagnostics_action` selects `start` or `collect` and defaults to `start`.
Set `run_diagnostics_enabled` to false to skip the role entirely.

`run_diagnostics_runtime_dir` stores the start marker and temporary collection
files. `run_diagnostics_output_dir` receives the final archive and defaults to
the runtime directory. Both directories are created with mode `0700`; collected
files use mode `0600`. Paths must be absolute, and the output directory cannot
be placed inside the temporary `collected` directory.

`run_diagnostics_log_directories` lists directories searched recursively for
`*.log` files. It defaults to common packaged and source-installed OVN and OVS
log locations. `run_diagnostics_log_bytes` limits the tail captured from each
file and defaults to 10 MiB.

`run_diagnostics_journal_lines` limits the journal to its most recent 100,000
lines by default. Set either limit to zero to omit that content.

The archive contains the system journal, process list, memory and filesystem
state, listening sockets, failed systemd units, kernel messages, and available
log tails. The required system tools must already be installed. Apply the role
with sufficient privileges to read the desired journals and logs. See
`defaults/main.yml` for all default values.

## Usage

Record the beginning of a workload:

```yaml
run_diagnostics_action: start
run_diagnostics_runtime_dir: /run/ovn-test/diagnostics
```

After the workload, collect a smaller log tail into a separate output
directory:

```yaml
run_diagnostics_action: collect
run_diagnostics_runtime_dir: /run/ovn-test/diagnostics
run_diagnostics_output_dir: /var/tmp/ovn-test-results
run_diagnostics_log_bytes: 1048576
run_diagnostics_log_directories:
  - /var/log/ovn
  - /var/log/openvswitch
```
