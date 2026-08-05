# ovn_test_pki

## Purpose

Create and distribute TLS credentials for OVN tests. The role generates a
short-lived test certificate authority and one endpoint certificate, stages the
endpoint private key, certificate, and CA certificate on the Ansible controller,
then installs the same credentials on the selected test hosts.

These credentials are deliberately simple and shared between test hosts. They
are not suitable for production use.

## Configuration

The role has two actions:

- `create`: generate the test CA and endpoint credentials on exactly one
  builder host, then fetch the usable credentials to the Ansible controller.
- `install`: copy previously created credentials from the controller to a test
  host and set their ownership and permissions.

Configure the role with these variables:

- `ovn_test_pki_enabled`: enable credential creation or installation. It
  defaults to `false`; a disabled action removes its corresponding credential
  directory.
- `ovn_test_pki_action`: `create` by default, or `install`.
- `ovn_test_pki_controller_dir`: private staging directory on the Ansible
  controller.
- `ovn_test_pki_remote_dir`: credential directory on builder and target hosts.
- `ovn_test_pki_service_group`: group allowed to read the installed private
  key. It defaults to `openvswitch` and is created when necessary.
- `ovn_test_pki_private_key`: installed endpoint private-key path.
- `ovn_test_pki_certificate`: installed endpoint-certificate path.
- `ovn_test_pki_ca_cert`: installed CA-certificate path.
- `ovn_test_pki_key_bits`: RSA key size, defaulting to `2048`.
- `ovn_test_pki_certificate_days`: certificate lifetime in days, defaulting to
  `1`.
- `ovn_test_pki_minimum_validity`: minimum remaining certificate lifetime in
  seconds. A bundle below this threshold is regenerated.
- `ovn_test_pki_ca_subject`: test CA certificate subject.
- `ovn_test_pki_endpoint_subject`: shared endpoint certificate subject.
- `ovn_test_pki_package_names`: package mapping passed to `distro_packages` to
  install OpenSSL on builders and target hosts.

All credential paths must be distinct files beneath `ovn_test_pki_remote_dir`,
and their basenames must be unique because controller staging is flat. Both
managed directories must be absolute paths other than `/`.

The role verifies certificate freshness, the certificate chain, and both key
pairs before reusing a builder bundle. A partial, mismatched, invalid, or nearly
expired bundle is regenerated as a unit. Installation verifies staged
credentials before replacing files already installed on a host.

The CA private key remains on the builder; only the endpoint key, endpoint
certificate, and CA certificate are staged and distributed. Installed private
keys use mode `0640`, while certificates use `0644`. See `defaults/main.yml` for
the default paths and package mapping.

## Usage

First create and stage the credentials on one builder host:

```yaml
ovn_test_pki_enabled: true
ovn_test_pki_action: create
```

Then install the staged credentials on every host that needs to participate in
the TLS-enabled test:

```yaml
ovn_test_pki_enabled: true
ovn_test_pki_action: install
```

The create action must target exactly one host. The install action can target
any number of hosts. Both stages must use the same
`ovn_test_pki_controller_dir` and credential file basenames. OVN service roles
can then use `ovn_test_pki_private_key`, `ovn_test_pki_certificate`, and
`ovn_test_pki_ca_cert` as their TLS paths.
