# ovn_load_balancer_groups

## Purpose

Create and manage OVN load-balancer groups. A group lets multiple load
balancers share the same logical-switch and logical-router attachments instead
of attaching every load balancer separately.

This role manages each group and its switch and router attachments. It leaves
the load balancers within a group unchanged so workloads can manage membership
independently. Groups not listed in `ovn_load_balancer_groups` are also left
unchanged.

## Configuration

Set `ovn_load_balancer_groups` to a list of group definitions. Each present
entry accepts:

- `id`: required unique identifier and OVN group name.
- `switches`: logical switches to which the group is attached.
- `routers`: logical routers to which the group is attached.
- `state`: `present` by default, or `absent` to remove the group identified by
  `id`.

Group IDs must be unique within the list.

For present entries, `switches` and `routers` are authoritative: attachments
omitted during reconfiguration are removed. Load-balancer membership is
preserved. Each group's changes are applied in one database transaction, and
identical reapplication does not report a change.

By default, configuration comes directly from `ovn_load_balancer_groups`. Set
`ovn_load_balancer_groups_path` to read generated configuration from a JSON file
on the managed system instead. The file may contain either the list itself or
an object with a `load_balancer_groups` field. See `defaults/main.yml` for the
default values.

## Usage

Create a group shared by two logical switches and an edge router:

```yaml
ovn_load_balancer_groups:
  - id: application-services
    switches:
      - application-a
      - application-b
    routers:
      - edge-router
```

Remove the group without changing other managed or unmanaged groups:

```yaml
ovn_load_balancer_groups:
  - id: application-services
    state: absent
```
