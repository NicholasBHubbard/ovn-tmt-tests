# ovn_load_balancers

## Purpose

Create and manage OVN load balancers. A load balancer maps one or more virtual
IP addresses and optional ports to backend addresses, then applies those rules
to selected logical switches and routers.

Each load balancer has a stable `id` stored in its OVN external IDs. Reusing
that ID updates the same database row even if its display name changes. Set
`state: absent` to remove it. Load balancers not listed in
`ovn_load_balancers` are left unchanged.

## Configuration

Set `ovn_load_balancers` to a list of load-balancer definitions. Each present
entry accepts:

- `id`: required stable identifier.
- `name`: optional OVN display name, defaulting to `id`.
- `protocol`: `tcp` by default, or `udp` or `sctp`.
- `vips`: mapping of virtual addresses to one or more backend addresses.
- `options`: mapping of OVN load-balancer options. Boolean values are stored as
  lowercase `true` or `false`.
- `selection_fields`: fields OVN may hash when choosing a backend. Supported
  values are `eth_src`, `eth_dst`, `ip_src`, `ip_dst`, `ipv6_src`, `ipv6_dst`,
  `tp_src`, and `tp_dst`.
- `switches`: logical switches to which the load balancer is attached.
- `routers`: logical routers to which the load balancer is attached.
- `state`: `present` by default, or `absent` to remove the load balancer
  identified by `id`.

A VIP or backend uses `address` or `address:port` syntax. Enclose IPv6 addresses
in square brackets when a port is included. A backend value can be a single
string or a list; lists are stored as a comma-separated backend set.

For present entries, `name`, `protocol`, `vips`, `options`, `selection_fields`,
`switches`, and `routers` are authoritative. Values or attachments omitted
during reconfiguration are removed or reset to their defaults. Load-balancer
fields are replaced in one database transaction, and identical reapplication
does not report a change. Load-balancer IDs must be unique within the list. See
`defaults/main.yml` for the default value.

## Usage

Configure a TCP virtual service with two backends and attach it to a switch and
router:

```yaml
ovn_load_balancers:
  - id: web-service
    name: web-service
    protocol: tcp
    vips:
      "192.0.2.100:443":
        - "10.0.0.10:8443"
        - "10.0.0.11:8443"
    options:
      reject: true
    selection_fields:
      - ip_src
      - tp_src
    switches:
      - application
    routers:
      - edge-router
```

Remove the managed load balancer without affecting unlisted load balancers:

```yaml
ovn_load_balancers:
  - id: web-service
    state: absent
```
