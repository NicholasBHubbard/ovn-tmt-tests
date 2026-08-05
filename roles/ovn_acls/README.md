# ovn_acls

## Purpose

Create and manage OVN access-control rules. An ACL is a network
traffic rule attached to a logical switch or port group.

Each ACL has a stable `id`. Reusing that ID updates the existing ACL, including
moving it to another switch or port group. Set `state: absent` to remove it.
ACLs not listed in `ovn_acls` are left unchanged.

## Configuration

Set `ovn_acls` to a list of ACL definitions. Each present ACL requires:

- `id`: stable identifier used to find the ACL on later runs.
- `target`: logical switch or port-group name.
- `target_type`: `switch` (the default) or `port_group`.
- `direction`: `from-lport` for traffic entering a logical switch or `to-lport`
  for traffic leaving it.
- `priority`: integer from 0 through 32767; higher-priority rules take
  precedence.
- `match`: OVN match expression.
- `action`: `allow`, `allow-related`, `allow-stateless`, `drop`, `reject`, or
  `pass`.

Optional fields are `name`, `log`, `severity`, `meter`, `label`, `tier` (0
through 3), and `options`. Their previous values are cleared when omitted during
an update. Use `state: absent` with only the ACL's `id` to remove it.

## Usage

The role is normally applied as part of the larger OVN topology configuration:

```yaml
ovn_acls:
  - id: web-ingress
    target_type: port_group
    target: web-servers
    direction: to-lport
    priority: 1000
    match: 'tcp && tcp.dst == 443'
    action: allow-related
```
