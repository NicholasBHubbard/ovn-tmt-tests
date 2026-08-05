# ovn_endpoints

## Purpose

Create OVN logical switch ports and realize them as Linux network namespaces on
the requested hosts. Each local endpoint is connected to OVS with a veth pair,
giving tests a small host-like network stack that can send and receive traffic
through OVN.

The role has two modes. `ports` manages logical switch ports in the Northbound
database and is normally applied on a central node. `local` uses the
`ovs_endpoints` role to create or remove namespaces on each candidate host.
Higher-level multihost setup applies the same `ovn_endpoints` configuration in
both places.

Listed endpoints default to present. Setting `state: absent` removes their
logical port and local namespace; changing `host`, `switch`, or the OVS bridge
moves the managed state. Endpoints not listed in `ovn_endpoints` are left
unchanged.

## Configuration

The role accepts these top-level variables:

- `ovn_endpoints`: endpoint definitions to manage.
- `ovn_endpoints_mode`: `ports` for Northbound logical-port configuration or
  `local` for namespaces on the current host.
- `ovn_endpoints_bridge`: OVS bridge to which local endpoints are attached. It
  inherits `ovn_chassis_integration_bridge` when set and otherwise defaults to
  `br-int`.
- `ovn_endpoints_mtu`: default MTU for both ends of each veth pair.
- `ovn_endpoints_dhcp_timeout`: default time allowed to obtain a DHCPv4 lease.
- `ovn_endpoints_runtime_dir`: directory for managed DHCP state.

Each present endpoint normally defines:

- `name`: network namespace name.
- `host`: Ansible inventory name where the namespace should exist.
- `switch`: OVN logical switch containing the port.
- `iface_id`: logical switch port name and OVS interface identifier.
- `mac`: endpoint MAC address.
- `addresses`: IP addresses with prefixes to configure inside the namespace.
- `address_mode`: `static` by default, or `dynamic` to request an address from
  OVN.
- `interface`: optional interface name inside the namespace. It defaults to the
  endpoint name when that fits Linux's length limit, otherwise `eth0`.
- `mtu`: per-endpoint override for `ovn_endpoints_mtu`.
- `options`: logical switch port options. Omitted options are cleared when the
  endpoint is reapplied.
- `routes`: routes with required `to` and optional `via`, `family`, `metric`,
  and `table` fields.
- `dhcpv4_options` and `dhcpv6_options`: stable IDs managed by the
  `ovn_dhcp_options` role and attached to the logical switch port.
- `dhcp4`: whether to obtain and maintain an actual DHCPv4 lease inside the
  namespace.
- `dhcp_timeout`: per-endpoint DHCP timeout override.
- `state`: `present` by default, or `absent` to remove the endpoint.

Reapplying an unchanged static endpoint preserves its namespace and veth
identity while refreshing managed addresses and routes. A managed DHCPv4 client
is restarted so it obtains a fresh lease. DHCPv6 option references are
supported, but the role does not run a DHCPv6 client.

See `defaults/main.yml` for the default values.

## Usage

Define the complete endpoint once and let higher-level orchestration apply it
in both role modes:

```yaml
ovn_endpoints:
  - name: web-1
    host: compute-1
    switch: application
    iface_id: web-1
    mac: "02:00:00:00:00:10"
    addresses:
      - 192.0.2.10/24
    routes:
      - to: default
        via: 192.0.2.1
    options:
      requested-chassis: compute-1
```

For an endpoint that obtains an IPv4 lease from OVN:

```yaml
ovn_endpoints:
  - name: dynamic-1
    host: compute-1
    switch: application
    iface_id: dynamic-1
    mac: "02:00:00:00:00:11"
    address_mode: dynamic
    addresses: []
    dhcpv4_options: application-ipv4
    dhcp4: true
```
