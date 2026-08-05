# ovn_chassis

## Purpose

Configure an existing host as an OVN chassis and start `ovn-controller`. The
role tells the controller how to reach the Southbound database, which address
and encapsulation to use for tunnels, and which OVS bridges and provider
networks belong to the chassis.

The role does not provision the host or create the OVN central databases. OVN
must already be installed, OVS must be running, and the configured Southbound
database must be reachable. Apply `ovn_install` before this role in the same
play so its installed paths are available when no controller service exists.
The larger chassis setup handles OVN installation and OVS setup before applying
this role.

## Configuration

The role accepts these `ovn_chassis_*` variables:

- `ovn_chassis_remote`: Southbound database connection string.
- `ovn_chassis_sb_port`: port used by the default local connection string.
- `ovn_chassis_name`: chassis name registered in the Southbound database.
- `ovn_chassis_encap_type`: tunnel encapsulation type, such as `geneve`.
- `ovn_chassis_encap_ip`: local address used for tunnel traffic.
- `ovn_chassis_integration_bridge`: integration bridge used by `ovn-controller`.
  It defaults to `br-int`.
- `ovn_chassis_bridges`: additional OVS bridges to ensure exist.
- `ovn_chassis_bridge_mappings`: provider-network-to-bridge mappings, such as
  `public:br-ex`.
- `ovn_chassis_cms_options`: chassis options consumed by higher-level systems,
  including `enable-chassis-as-gw` for a gateway chassis.
- `ovn_chassis_monitor_all`: whether `ovn-controller` monitors all Southbound
  database records.
- `ovn_chassis_ready_timeout` and `ovn_chassis_ready_delay`: controller
  connection polling controls.

See `defaults/main.yml` for the default values.

Reapplying the role replaces the chassis connection and identity settings.
Empty CMS options and bridge mappings are removed, and disabling monitor-all
removes that setting. The integration bridge and bridges listed in
`ovn_chassis_bridges` are created when missing; bridges removed from the list
are not deleted.

## Usage

Configure the role for each existing inventory host that should become a
chassis:

```yaml
ovn_chassis_remote: tcp:192.0.2.10:6642
ovn_chassis_name: compute-1
ovn_chassis_encap_ip: 192.0.2.21
ovn_chassis_integration_bridge: br-ovn
ovn_chassis_bridges:
  - br-ex
ovn_chassis_bridge_mappings: public:br-ex
ovn_chassis_cms_options:
  - enable-chassis-as-gw
```

For TLS, set `ovn_chassis_remote` to an `ssl:` endpoint and configure the OVS
client credentials through the `ovs_setup_ssl_*` variables before applying the
role.
