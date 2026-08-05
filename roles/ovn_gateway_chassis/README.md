# ovn_gateway_chassis

## Purpose

Assign one or more OVN chassis to logical router ports for gateway traffic. OVN
uses the assignment priority to select the active chassis and can use lower
priority assignments as backups.

The role manages `Gateway_Chassis` rows in the OVN Northbound database. It does
not configure the chassis itself or create logical router ports. Each target
router port must already exist. OVN accepts an assignment before the named
chassis is registered, but the assignment becomes operational only after a
matching chassis exists. The `ovn_chassis` role can perform that configuration
as part of a larger topology setup.

Each assignment has a stable `id`. Reusing that ID updates the chassis,
priority, or router-port attachment without replacing the database row. Setting
`state: absent` removes the assignment from its router port. Assignments not
listed in `ovn_gateway_chassis` are left unchanged.

## Configuration

Set `ovn_gateway_chassis` to a list of gateway assignments. Each present entry
accepts:

- `id`: required stable identifier for the assignment.
- `router_port`: required logical router port receiving the assignment.
- `chassis`: required OVN chassis name.
- `priority`: integer from `0` through `32767`, defaulting to `0`. Higher values
  are preferred.
- `state`: `present` by default, or `absent` to remove the assignment identified
  by `id`.

Assignment IDs must be unique within the list. See `defaults/main.yml` for the
default value.

## Usage

Assign a preferred and backup chassis to the same logical router port:

```yaml
ovn_gateway_chassis:
  - id: public-gateway-primary
    router_port: public-router-port
    chassis: gateway-1
    priority: 50
  - id: public-gateway-backup
    router_port: public-router-port
    chassis: gateway-2
    priority: 40
```

Remove one assignment while leaving all other assignments untouched:

```yaml
ovn_gateway_chassis:
  - id: public-gateway-backup
    state: absent
```
