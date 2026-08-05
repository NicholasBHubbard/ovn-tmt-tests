# ovn_central

## Purpose

Configure the OVN Northbound and Southbound databases and `ovn-northd`. The
role supports a standalone central node or a multi-node database cluster, with
either TCP or TLS for both client and clustered Raft connections.

The role expects OVN and OVS to already be installed and OVS to be running.
Apply `ovn_install` before this role in the same play so it can provide the
installed control-script and runtime paths. Higher-level central-node setup
normally handles these prerequisites.

## Configuration

The role accepts these `ovn_central_*` variables:

- `ovn_central_nb_port`: Northbound database client port.
- `ovn_central_sb_port`: Southbound database client port.
- `ovn_central_nb_raft_port`: Northbound cluster port.
- `ovn_central_sb_raft_port`: Southbound cluster port.
- `ovn_central_listen_address`: address on which the databases accept clients.
- `ovn_central_address`: this node's cluster address. It defaults to
  `ansible_host`, then the inventory name.
- `ovn_central_cluster_members`: ordered list of central-node addresses. An
  empty list selects standalone mode; the first address initializes the
  cluster and the remaining addresses join it. The list must contain this
  node's `ovn_central_address`.
- `ovn_central_cluster_join_timeout`: time allowed for a follower to reach the
  initial cluster member.
- `ovn_central_ready_timeout` and `ovn_central_ready_delay`: database and
  `ovn-northd` readiness polling controls.
- `ovn_central_reconcile_cluster_members`: remove members that are no longer
  in `ovn_central_cluster_members` when configuring the first member.
- `ovn_central_ssl_enabled`: whether database listeners and `ovn-northd`
  connections, including Raft connections, use TLS instead of TCP.
- `ovn_central_ssl_private_key`, `ovn_central_ssl_certificate`, and
  `ovn_central_ssl_ca_cert`: TLS credential paths on each central node.
- `ovn_central_log_level`: `ovn-northd` file log level.

IPv6 addresses are rendered in the bracketed form required by OVSDB. When
firewalld is running, the role opens the configured client and Raft ports.

See `defaults/main.yml` for the default values.

## Usage

For one standalone node, leave `ovn_central_cluster_members` empty. For a
cluster, higher-level multihost setup normally builds the member list from its
central-node inventory groups before applying the role. Set
`ovn_central_address` in a host's inventory variables when `ansible_host` is not
the address other cluster members should use.

The equivalent role configuration is:

```yaml
- role: ovn_central
  ovn_central_cluster_members:
    - 192.0.2.10
    - 192.0.2.11
    - 192.0.2.12
  ovn_central_ssl_enabled: true
  ovn_central_ssl_private_key: /run/ovn-test-pki/private-key.pem
  ovn_central_ssl_certificate: /run/ovn-test-pki/certificate.pem
  ovn_central_ssl_ca_cert: /run/ovn-test-pki/ca-cert.pem
```

The TLS files must exist on every central node before applying the role.

Reapplying the role updates local client listeners, `ovn-northd` connections,
the log level, and cluster membership. Changing an existing member's Raft
address, port, or protocol requires reprovisioning that member.

See the [`ovn-ctl` documentation](https://www.ovn.org/support/dist-docs/ovn-ctl.8.html)
for the underlying service options and the
[OVSDB documentation](https://docs.openvswitch.org/en/stable/ref/ovsdb.7/)
for database endpoint and clustering behavior.
