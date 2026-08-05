# ovn_routers

## Purpose

Create and manage OVN logical routers. Logical routers connect logical networks
and hold routing-related objects such as router ports, static routes, and NAT
rules.

Set `state: absent` to remove a router. Routers not listed in `ovn_routers` are
left unchanged. This role manages routers and their options; separate roles
manage the objects attached to them.

## Configuration

Set `ovn_routers` to a list of logical-router definitions. Each entry accepts:

- `name`: required logical router name.
- `enabled`: optional administrative state. Set it to `false` to drop traffic
  through the router. Omitting it leaves OVN's default enabled behavior.
- `options`: optional mapping of logical router options. Boolean values are
  stored as lowercase `true` or `false`.
- `state`: `present` by default, or `absent` to remove the router identified by
  `name`.

For present routers, `enabled` and `options` are authoritative. An omitted
`enabled` value and omitted options are cleared, while routers not listed remain
untouched. Each router is changed in one database transaction, and reapplying
identical configuration reports no change.
Removing a router also removes the objects owned by that router, so dependent
topology should be reconfigured accordingly. See `defaults/main.yml` for the
default value.

## Usage

Create an edge router and configure OVN router options:

```yaml
ovn_routers:
  - name: edge-router
    enabled: true
    options:
      chassis: gateway-1
      dynamic_neigh_routers: true
      mac_binding_age_threshold: 5
```

Remove a router without changing other logical routers:

```yaml
ovn_routers:
  - name: edge-router
    state: absent
```
