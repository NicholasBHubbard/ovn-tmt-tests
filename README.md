# ovn-tmt-tests

This project provides reusable and configurable [tmt](https://tmt.readthedocs.io/) plans, tests, and [Ansible](https://docs.ansible.com/) automation, for creating [OVN](https://www.ovn.org/en/) test deployments.

DISCLAIMER: This project is currently under development and is not ready for real use!

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

### `.fmf/`

Root fmf metadata for the tmt test tree.

### `ansible.cfg`

Ansible configuration for this repository. It points Ansible at the local
`roles/` directory so playbooks can reference roles by name.

### `plans/`

tmt plans that define how tests are provisioned, prepared, discovered, and
executed.

### `playbooks/`

Ansible playbooks used by tmt `prepare` steps.

### `roles/`

Reusable Ansible roles.

### `tests/`

tmt test metadata and verification scripts.

`tests/self/` contains tests for this repository's own roles and topology examples.
