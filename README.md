# ovn-tmt-tests

DISCLAIMER: This project is currently under development and is not ready for real use!

This project provides reusable and configurable [tmt](https://tmt.readthedocs.io/)
plans, tests, and [Ansible](https://docs.ansible.com/) automation for creating
[OVN](https://www.ovn.org/en/) test deployments.

This project currently targets Linux test systems only.

## How it works

A tmt plan provisions guests, uses Ansible roles to install and configure OVN
and OVS, selects pytest workloads, and can collect diagnostics. Shared Python
helpers in [`tests/lib/ovn_test`](tests/lib/ovn_test/) let workloads drive and
inspect the resulting deployment.

Plans may use containers, virtual machines, or externally provisioned systems.
Reusable roles and test helpers must not depend on the provisioning method.

## Test families

- `self` verifies the repository's own roles, Python library, and configuration.
- `ovn-ci` covers compilation, unit, distcheck, and system-test variants.
- `ovn-fake-multinode` covers OVN behavior across multiple hosts.
- `ovn-scale-testing` covers density, network-policy, and service workloads.
- `failures` contains intentionally failing tests and is disabled by default.

## Requirements

- Ansible
- Ansible collections:
  - `ansible.posix`
  - `community.general`
- Python 3.9 or newer
- pytest
- PyYAML
- tmt with the `provision-container` and `provision-virtual` plugins

## Running plans

List available plans with `tmt plan ls`. Run one by its full name:

```sh
tmt run --all plan --name '^/plans/ovn-ci/unit-gcc$'
```

## Configuration

Plans define top-down defaults with `OTT_` environment variables. Override a
setting for one run with tmt's `--environment` option:

```sh
tmt run --environment OTT_INSTALL_METHOD=distro --all \
  plan --name '^/plans/ovn-scale-testing/density-light$'
```

## Development

Put reusable system configuration in an Ansible role and reusable test
behavior in `tests/lib/ovn_test`. Keep scenario-specific setup and assertions
with the test that owns them, and add a self-test for new reusable behavior.

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

tmt test metadata and pytest workloads.

[`tests/lib/ovn_test/`](tests/lib/ovn_test/) contains reusable test helpers, and
[`tests/self/`](tests/self/) contains tests for this repository itself.

## AI Usage

This code was developed in part with AI tooling such as Claude Code and Codex.

## License

This repository is licensed under the Apache 2.0 license.
