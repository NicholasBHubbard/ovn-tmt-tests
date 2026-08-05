# ovn_localnet_ports

## Purpose

Create and manage OVN localnet ports. A localnet port connects a logical switch
to a physical Layer 2 network that is locally reachable from one or more
chassis.

This role creates the OVN connection point. Each participating chassis must
separately map the port's physical network name to an OVS bridge. The
`ovn_chassis` role can configure those bridge mappings as part of a larger
topology setup.

Existing ports can be moved between logical switches without replacing their
database rows. Set `state: absent` to remove a port. Ports not listed in
`ovn_localnet_ports` are left unchanged.

## Configuration

Set `ovn_localnet_ports` to a list of localnet-port definitions. Each present
entry accepts:

- `name`: required unique logical switch port name.
- `switch`: required logical switch receiving the port.
- `network`: required physical network name. It must match a chassis bridge
  mapping for traffic to reach that network.
- `tag`: optional VLAN tag request from `0` through `4095`. Omit it for an
  untagged connection.
- `options`: optional mapping of additional OVN localnet-port options. Boolean
  values are stored as lowercase `true` or `false`. Set the physical network
  through `network`, not `options.network_name`.
- `state`: `present` by default, or `absent` to remove the port identified by
  `name`.

For present entries, `switch`, `network`, `tag`, and `options` are
authoritative. Omitting `tag` clears the VLAN tag request, and omitting an option
removes it. Any previously allocated VLAN tag is also cleared when `tag` is
omitted. The role sets the port type to `localnet`, its address to `unknown`, and
its options to the configured `network_name` plus `options`. Each port is updated
in one database transaction, and identical reapplication does not report a
change. See `defaults/main.yml` for the default value.

## Usage

Connect a logical switch to VLAN 100 on the `public` physical network:

```yaml
ovn_localnet_ports:
  - name: public-localnet
    switch: public-switch
    network: public
    tag: 100
```

Remove the port without changing other localnet ports:

```yaml
ovn_localnet_ports:
  - name: public-localnet
    state: absent
```
