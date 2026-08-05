# ovn_router_ports

## Purpose

Connect OVN logical routers to logical switches. Each attachment consists of a
logical router port and a matching logical switch port of type `router`.

Existing attachments can be moved between routers or switches without replacing
their database rows. Set `state: absent` to remove both ports. Attachments not
listed in `ovn_router_ports` are left unchanged.

This role manages switch-to-router attachments. It does not create peer ports
that connect two logical routers directly.

## Configuration

Set `ovn_router_ports` to a list of attachment definitions. Each present entry
accepts:

- `name`: required unique logical router port name.
- `router`: required logical router receiving the router port.
- `switch`: required logical switch receiving the matching switch port.
- `switch_port`: required unique logical switch port name.
- `mac`: required MAC address belonging to the router port.
- `networks`: optional list of router addresses in address-and-prefix form, such
  as `192.0.2.1/24` or `2001:db8::1/64`.
- `options`: optional mapping of logical router port options. Boolean values are
  stored as lowercase `true` or `false`.
- `switch_options`: optional mapping of matching logical switch port options.
  The role manages the reserved `router-port` option itself.
- `state`: `present` by default, or `absent` to remove the attachment.

An absent entry needs `name` and `switch_port` so both sides of the attachment
can be removed. The referenced router and switch must already exist when an
attachment is present. A larger topology configuration normally creates them
before applying router ports.

For present entries, every field is authoritative. Omitted networks and options
are cleared. The matching switch port is configured with type `router`, address
`router`, and a `router-port` option pointing to `name`, in addition to any
`switch_options`. Each attachment is changed in one database transaction, and
reapplying identical configuration reports no change. See `defaults/main.yml`
for the default value.

## Usage

Connect an application switch to an edge router with IPv4 and IPv6 addresses:

```yaml
ovn_router_ports:
  - name: edge-application
    router: edge-router
    switch: application
    switch_port: application-edge
    mac: "02:00:00:00:10:01"
    networks:
      - 192.0.2.1/24
      - 2001:db8::1/64
    options:
      gateway_mtu: 1400
```

Remove both ports without changing other attachments:

```yaml
ovn_router_ports:
  - name: edge-application
    switch_port: application-edge
    state: absent
```
