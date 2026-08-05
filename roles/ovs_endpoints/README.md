# ovs_endpoints

## Purpose

Create host-like test endpoints as Linux network namespaces attached directly
to existing Open vSwitch bridges. Each endpoint uses a veth pair, with one end
inside the namespace and the other added as an OVS port.

The role manages local namespace and OVS state only. It does not create OVS
bridges or OVN logical switch ports. The `ovs_bridges` role can create the
bridges, while `ovn_endpoints` can coordinate these local endpoints with OVN
logical ports.

Listed endpoints default to present. Setting `state: absent` removes the
namespace, veth pair, and OVS port. Changing `host` or `bridge` moves the
managed endpoint, while unlisted endpoints are left unchanged.

## Configuration

Set `ovs_endpoints` to a list of endpoint definitions. Each present endpoint
accepts:

- `name`: required network namespace name and stable endpoint identifier.
- `host`: required Ansible inventory name where the endpoint should exist.
- `bridge`: required existing OVS bridge receiving the host-side veth.
- `mac`: required MAC address for the namespace interface.
- `iface_id`: optional OVS `iface-id` external ID. When the bridge is an OVN
  integration bridge, this normally identifies a logical switch port managed
  elsewhere.
- `addresses`: IP addresses with prefixes to configure inside the namespace.
- `routes`: routes with required `to` and optional `via`, `family`, `metric`,
  and `table` fields. The address family is inferred when `family` is omitted.
- `interface`: optional interface name inside the namespace. It defaults to
  `name` when that fits Linux's 15-character limit, otherwise `eth0`.
- `mtu`: optional per-endpoint override for `ovs_endpoints_mtu`.
- `state`: `present` by default, or `absent` to remove the endpoint identified
  by `name`.

`ovs_endpoints_mtu` sets the default MTU for both ends of every veth pair and
defaults to `1500`.

Apply the same endpoint list to every candidate host when endpoints may move.
The selected host creates a present endpoint, while other hosts remove any
stale local instance. Reconfiguration preserves the namespace and veth identity
when the endpoint remains on the same host, including when it moves between OVS
bridges.

Managed global addresses and routes are authoritative, so omitted values are
removed. Omitting `iface_id` removes a previously managed interface ID.
Reapplying identical configuration does not change the endpoint. The namespace
is expected to contain exactly one managed veth interface. Open vSwitch, Linux
network namespaces, and every referenced bridge must already be available. See
`defaults/main.yml` for the default values.

## Usage

Attach two endpoints to an existing test bridge:

```yaml
ovs_endpoints:
  - name: client
    host: compute-1
    bridge: br-test
    mac: "02:00:00:00:00:10"
    addresses:
      - 192.0.2.10/24
    routes:
      - to: default
        via: 192.0.2.1
  - name: server
    host: compute-2
    bridge: br-test
    mac: "02:00:00:00:00:20"
    addresses:
      - 192.0.2.20/24
```

Remove an endpoint from every candidate host:

```yaml
ovs_endpoints:
  - name: client
    state: absent
```
