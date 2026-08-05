# multihost_driver

## Purpose

Allow tests running on one tmt guest to connect to the other guests. The role
installs Ansible and an SSH client on the driver guest, creates an SSH key there,
and fetches its public key to the machine running tmt.

The larger multihost setup installs that public key on every guest after this
role runs. The role assumes the configured SSH user already exists and does not
provision the guests themselves.

## Configuration

The role accepts these `multihost_driver_*` variables:

- `multihost_driver_user`: existing account used for cross-guest SSH access.
- `multihost_driver_runtime_dir`: directory used on the driver guest.
- `multihost_driver_key_path`: private-key path on the driver guest.
- `multihost_driver_controller_public_key_path`: temporary public-key path on
  the machine running tmt and Ansible.
- `multihost_driver_package_names`: Ansible and SSH client packages for each
  supported package manager.

See `defaults/main.yml` for the default values.

## Usage

Apply the role to the guest that will drive the test:

```yaml
- role: multihost_driver
  multihost_driver_user: root
  multihost_driver_runtime_dir: /run/ovn-tmt-tests/multihost-driver
```

Higher-level orchestration should then authorize the fetched public key on the
other guests before the test begins.
