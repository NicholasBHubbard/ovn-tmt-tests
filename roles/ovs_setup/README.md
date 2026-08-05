# ovs_setup

## Purpose

Start and configure an existing Open vSwitch installation. The role verifies
that the OVS command-line tools are available, starts OVS, optionally creates
bridges through the `ovs_bridges` role, and configures or clears OVS SSL
settings.

The role does not install packages, clone source, or build OVS. OVN topologies
normally obtain their matching OVS installation through the `ovn_install` role.
OVS-only tests must install OVS through their provisioning configuration before
applying this role.

## Configuration

`ovs_setup_bridges` accepts the bridge definitions supported by the
`ovs_bridges` role and defaults to empty.

When `ovs_setup_ssl_enabled` is true, the role configures OVS with
`ovs_setup_ssl_private_key`, `ovs_setup_ssl_certificate`, and
`ovs_setup_ssl_ca_cert`; those files must already exist. When SSL is disabled,
which is the default, existing OVS SSL configuration is cleared.

`ovs_setup_service_name` defaults to `auto`, which selects
`openvswitch.service` or `openvswitch-switch.service` when available. Set it to
an explicit service name to require that unit, or to an empty string to use
`ovs-ctl`. `ovs_setup_service_enabled` controls whether a selected service is
enabled. `ovs_setup_ovs_ctl_path` accepts an explicit script path and defaults
to deterministic package and source installation locations.

Each application reconciles the requested bridges and SSL settings with the
current OVSDB state. `ovs_setup_updated` reports whether that application
changed the service, bridges, or SSL configuration. See `defaults/main.yml` for
all default values.

## Usage

Start OVS and create two bridges:

```yaml
ovs_setup_bridges:
  - br-int
  - br-ex
```

Configure OVS to use existing TLS credentials:

```yaml
ovs_setup_ssl_enabled: true
ovs_setup_ssl_private_key: /etc/openvswitch/ovs-privkey.pem
ovs_setup_ssl_certificate: /etc/openvswitch/ovs-cert.pem
ovs_setup_ssl_ca_cert: /etc/openvswitch/cacert.pem
```
