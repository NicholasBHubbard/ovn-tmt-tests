# ovn_sb_convergence

## Purpose

Wait for OVN Northbound changes to appear in the Southbound database, then
verify that the expected logical datapaths and ports are present and that
removed objects are absent.

This checks Southbound database convergence. It does not wait for every chassis
to process the resulting configuration. The role does not change the topology
and always reports no Ansible change.

## Configuration

Configure expected Southbound object names with:

- `ovn_sb_convergence_datapaths`: names stored in the `name` external ID of
  `Datapath_Binding` rows.
- `ovn_sb_convergence_ports`: logical port names in `Port_Binding` rows.
- `ovn_sb_convergence_absent_datapaths`: datapath names that must no longer
  exist.
- `ovn_sb_convergence_absent_ports`: logical port names that must no longer
  exist.

At least one expectation must be provided, either directly or through
`ovn_sb_convergence_state_path`. The state file is read from the managed system
and may contain the fields directly or under a `southbound` field. Values from
the state file take precedence over directly configured expectations.

`ovn_sb_convergence_timeout` controls the maximum wait in seconds and defaults
to 120. `ovn_sb_convergence_nbctl` and `ovn_sb_convergence_sbctl` are command
lists for accessing the Northbound and Southbound databases. They default to
`ovn-nbctl` and `ovn-sbctl`; add database or TLS options when the defaults cannot
reach the databases. See `defaults/main.yml` for all default values.

## Usage

Wait for a logical switch and its port to reach the Southbound database while
also confirming that an old port has been removed:

```yaml
ovn_sb_convergence_datapaths:
  - application
ovn_sb_convergence_ports:
  - application-server
ovn_sb_convergence_absent_ports:
  - old-application-server
ovn_sb_convergence_timeout: 300
```

Read generated expectations from a file on the managed system:

```yaml
ovn_sb_convergence_state_path: /run/ovn-test/topology.json
```
