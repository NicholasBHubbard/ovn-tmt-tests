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
