# ovn-tmt-tests

This project provides reusable and configurable [tmt](https://tmt.readthedocs.io/) plans, tests, and [Ansible](https://docs.ansible.com/) automation, for creating [OVN](https://www.ovn.org/en/) test deployments.

DISCLAIMER: This project is currently under development and is not ready for real use!

## Requirements

- [tmt](https://tmt.readthedocs.io/) with `provision-container` and `provision-virtual` plugins
- [Ansible](https://docs.ansible.com/)
- Ansible collections:
  - [`ansible.posix`](https://docs.ansible.com/ansible/latest/collections/ansible/posix/)
  - [`community.general`](https://docs.ansible.com/ansible/latest/collections/community/general/)
- Bash

Install the collections with:

```sh
ansible-galaxy collection install ansible.posix community.general
```

### Virtual guests

Plans that provision virtual guests require QEMU/KVM, the system libvirt QEMU
driver, and libvirt's default network. On Fedora, install them with:

```sh
sudo dnf install libvirt-client libvirt-daemon-config-network \
    libvirt-daemon-kvm qemu-kvm
sudo systemctl enable --now virtqemud.socket virtnetworkd.socket
```

Multihost plans use `qemu:///system` so their guests share a network. Grant the
user running tmt access to it, then log out and back in:

```sh
sudo usermod -aG libvirt "$USER"
```

## Running plans

List available plans with `tmt plan ls`. Run one by its full name:

```sh
tmt run --all plan --name '^/plans/ovn-ci/unit-gcc$'
```

## Directory Layout

```text
.
├── .fmf/
├── ansible.cfg
├── plans/
├── playbooks/
├── roles/
└── tests/
```

### [`.fmf/`](.fmf/)

Root fmf metadata for the tmt test tree.

### [`ansible.cfg`](ansible.cfg)

Ansible configuration for this repository. It points Ansible at the local
`roles/` directory so playbooks can reference roles by name.

### [`plans/`](plans/)

tmt plans that define how tests are provisioned, prepared, discovered, and
executed.

### [`playbooks/`](playbooks/)

Ansible playbooks used by tmt [prepare](https://tmt.readthedocs.io/en/stable/plugins/prepare.html) steps.

### [`roles/`](roles/)

Reusable Ansible roles.

### [`tests/`](tests/)

tmt test metadata and verification scripts.

[`tests/self/`](tests/self/) contains tests for this repository's own roles and topology examples.
