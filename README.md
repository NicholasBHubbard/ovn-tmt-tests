# ovn-tmt-tests

This project provides reusable and configurable [tmt](https://tmt.readthedocs.io/) plans, tests, and [Ansible](https://docs.ansible.com/) automation, for creating [OVN](https://www.ovn.org/en/) test deployments.

DISCLAIMER: This project is currently under development and is not ready for real use!

## Requirements

- Ansible
- Ansible collections:
  - `ansible.posix`
  - `community.general`
- Bash
- libvirt
- Podman
- QEMU/KVM
- tmt with the `provision-container` and `provision-virtual` plugins

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

## AI Usage

This code was developed in part with AI tooling such as Claude Code and Codex.

## License

This repository is licensed under the Apache 2.0 license.
