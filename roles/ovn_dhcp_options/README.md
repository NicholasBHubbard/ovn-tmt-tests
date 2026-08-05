# ovn_dhcp_options

## Purpose

Create and manage reusable DHCP option sets in the OVN Northbound database.
Each option set describes an IPv4 or IPv6 subnet and the DHCP values OVN should
offer to ports on that subnet.

This role only manages `DHCP_Options` rows. A logical switch port uses an option
set when its `dhcpv4_options` or `dhcpv6_options` field refers to the option
set's `id`, normally through the `ovn_endpoints` role.

Each managed row has a stable `id`. Reusing that ID updates the existing row
without changing its UUID. Set `state: absent` to remove it. Rows not listed in
`ovn_dhcp_options` are left unchanged.

## Configuration

Set `ovn_dhcp_options` to a list of option-set definitions. Each present entry
accepts:

- `id`: required stable identifier used to find the row on later runs.
- `cidr`: required IPv4 or IPv6 subnet served by the option set.
- `options`: optional mapping of OVN DHCP option names to their values.
- `state`: `present` by default, or `absent` to remove the row identified by
  `id`.

Reapplying a present entry replaces its `cidr` and complete `options` mapping,
so options omitted from the new configuration are cleared. Boolean option
values are stored as `1` or `0`.

See `defaults/main.yml` for the default value.

## Usage

The role is normally applied as part of the larger OVN topology configuration:

```yaml
ovn_dhcp_options:
  - id: application-ipv4
    cidr: 192.0.2.0/24
    options:
      server_id: 192.0.2.1
      server_mac: "02:00:00:00:00:01"
      router: 192.0.2.1
      dns_server: 192.0.2.53
      lease_time: 3600
```

An endpoint can then refer to this option set by ID:

```yaml
ovn_endpoints:
  - name: application-1
    host: compute-1
    switch: application
    iface_id: application-1
    mac: "02:00:00:00:00:10"
    address_mode: dynamic
    addresses: []
    dhcpv4_options: application-ipv4
```
