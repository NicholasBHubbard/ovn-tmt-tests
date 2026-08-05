# ovn_switches

## Purpose

Create and manage OVN logical switches. Logical switches provide the Layer 2
networks to which logical switch ports, router ports, and other OVN topology
objects can be attached.

Set `state: absent` to remove a switch. Switches not listed in `ovn_switches`
are left unchanged. Removing a switch also removes the logical switch ports it
contains, so dependent topology should be reconfigured accordingly.

## Configuration

Set `ovn_switches` to a list of logical-switch definitions. Each entry accepts:

- `name`: required logical switch name.
- `other_config`: optional mapping of OVN logical-switch configuration. Boolean
  values are stored as lowercase `true` or `false`.
- `state`: `present` by default, or `absent` to remove the switch identified by
  `name`.

For present switches, `other_config` is authoritative. Options omitted from a
later configuration are cleared. Switch creation and configuration are applied
in one database transaction, and identical reapplication reports no change. A
larger topology configuration can defer deletion until dependent objects have
been moved or removed. See `defaults/main.yml` for the default value.

## Usage

Create a logical switch with subnet and multicast-snooping configuration:

```yaml
ovn_switches:
  - name: application
    other_config:
      subnet: 192.0.2.0/24
      exclude_ips: 192.0.2.1..192.0.2.10
      mcast_snoop: true
```

Remove a switch without changing other logical switches:

```yaml
ovn_switches:
  - name: application
    state: absent
```
