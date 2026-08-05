# ovn_nat

## Purpose

Create and manage OVN NAT rules. NAT rules translate addresses as traffic
passes through an OVN logical router. They can provide source NAT, destination
NAT, or bidirectional translation for an address.

Each rule has a stable `id` stored in its OVN external IDs. Reusing that ID
updates the same database row, including moving it to another logical router.
Set `state: absent` to remove it. Rules not listed in `ovn_nat_rules` are left
unchanged.

## Configuration

Set `ovn_nat_rules` to a list of NAT-rule definitions. Each present entry
accepts:

- `id`: required unique identifier.
- `router`: required logical router receiving the rule.
- `type`: required translation type: `snat`, `dnat`, or `dnat_and_snat`.
- `external_ip`: required externally visible address.
- `logical_ip`: required internal address or network. Its exact accepted form
  depends on the NAT type.
- `logical_port`: optional logical switch port where `logical_ip` resides. Used
  with `external_mac` for distributed NAT.
- `external_mac`: optional MAC address for distributed NAT.
- `external_port_range`: optional source-port range in `first-last` form.
- `gateway_port`: optional logical router port on which to apply the rule.
- `allowed_ext_ips`: optional address-set name restricting the external
  addresses to which the rule applies.
- `exempted_ext_ips`: optional address-set name exempting external addresses
  from the rule. It cannot be combined with `allowed_ext_ips`.
- `match`: optional additional OVN match expression.
- `priority`: optional match priority from `0` through `32767`, defaulting to
  `0`. It matters only when `match` is set.
- `options`: optional mapping of OVN NAT options. Boolean values are stored as
  lowercase `true` or `false`.
- `state`: `present` by default, or `absent` to remove the rule identified by
  `id`.

The referenced router, logical port, gateway port, and address sets must already
exist when needed. A larger topology configuration normally creates these
objects before applying NAT rules.

For present entries, all fields other than `id` are authoritative. Optional
fields and options omitted during reconfiguration are cleared, while rules not
listed remain untouched. Each rule is updated in one database transaction, and
identical reapplication does not report a change. Rule IDs must be unique within
the list. See `defaults/main.yml` for the default value.

## Usage

Give an internal endpoint a bidirectional floating address:

```yaml
ovn_nat_rules:
  - id: web-floating-ip
    router: edge-router
    type: dnat_and_snat
    external_ip: 192.0.2.100
    logical_ip: 10.0.0.10
    logical_port: web-port
    external_mac: "02:00:00:00:10:10"
    options:
      add_route: true
```

Remove the managed rule without changing other NAT rules:

```yaml
ovn_nat_rules:
  - id: web-floating-ip
    state: absent
```
