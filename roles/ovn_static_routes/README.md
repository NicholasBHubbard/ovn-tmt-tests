# ovn_static_routes

## Purpose

Create and manage static routes on OVN logical routers. Each route has a stable
`id` stored in its OVN external IDs. Reusing that ID updates the same database
row, including moving it to another logical router.

Set `state: absent` to remove a managed route. Routes not listed in
`ovn_static_routes`, including routes created outside this role, are left
unchanged.

## Configuration

Set `ovn_static_routes` to a list of route definitions. Each present entry
accepts:

- `id`: required unique identifier.
- `router`: required logical router receiving the route.
- `prefix`: required destination or source prefix to match.
- `nexthop`: required next-hop address.
- `policy`: optional lookup policy, defaulting to `dst-ip`. Use `src-ip` for a
  source-based route.
- `route_table`: optional route-table name.
- `output_port`: optional logical router port through which to send traffic.
- `bfd`: optional existing BFD session identified by its `logical_port` and
  `dst_ip`. The destination must equal `nexthop`, and its logical port must
  equal `output_port` when both are configured.
- `selection_fields`: optional list of packet fields OVN may hash when choosing
  among equal-cost routes. Supported fields are `eth_dst`, `eth_src`, `ip_dst`,
  `ip_proto`, `ip_src`, `ipv6_dst`, `ipv6_src`, `tp_dst`, and `tp_src`.
- `options`: optional mapping of OVN static-route options. Boolean values are
  stored as lowercase `true` or `false`.
- `state`: `present` by default, or `absent` to remove the route identified by
  `id`.

An absent entry needs only `id`. The referenced logical router and optional
output port must already exist when a route is present. An output port must
belong to the route's logical router. A referenced BFD session must also already
exist. A larger topology configuration normally creates these objects before
applying static routes.

For present entries, all fields other than `id` are authoritative. Omitting
`policy` restores `dst-ip`, while omitting `route_table` or `output_port` clears
the corresponding value. Omitting `bfd`, `selection_fields`, or `options` also
clears that configuration from the route; the role does not delete the
independently managed BFD session. Route creation, movement, and configuration
are applied atomically. Reapplying identical configuration reports no change.
Route IDs must be unique within the list. See `defaults/main.yml` for the
default value.

## Usage

Add a default route through an edge router port:

```yaml
ovn_static_routes:
  - id: edge-default
    router: edge-router
    prefix: 0.0.0.0/0
    nexthop: 192.0.2.1
    output_port: edge-uplink
    selection_fields:
      - ip_src
      - ip_dst
    options:
      ecmp_symmetric_reply: true
```

Add a source-based route to a named route table:

```yaml
ovn_static_routes:
  - id: application-source
    router: edge-router
    prefix: 10.0.0.0/24
    nexthop: 192.0.2.2
    policy: src-ip
    route_table: application
```

Associate an existing BFD session with a route:

```yaml
ovn_static_routes:
  - id: monitored-default
    router: edge-router
    prefix: 0.0.0.0/0
    nexthop: 192.0.2.1
    output_port: edge-uplink
    bfd:
      logical_port: edge-uplink
      dst_ip: 192.0.2.1
```

Remove a managed route without changing other routes:

```yaml
ovn_static_routes:
  - id: edge-default
    state: absent
```
