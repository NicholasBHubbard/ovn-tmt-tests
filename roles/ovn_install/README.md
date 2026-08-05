# ovn_install

## Purpose

Install OVN and its matching OVS build on a test host. The role can use the
host's package repositories, specific package files, an existing source tree, a
Git revision, or a previously built installation artifact.

The role only installs software. It does not create OVN databases, start
central services, or configure a chassis. After installation it publishes the
`ovn_install_ovn_ctl_path`, `ovn_install_nb_control_socket`, and
`ovn_install_sb_control_socket` facts for roles that perform those tasks. It
also verifies that the matching OVS command-line tools are available and
records installation facts so later roles in the same Ansible run do not repeat
work already performed.

## Configuration

`ovn_install_method` selects one of five installation methods and defaults to
`distro`:

- `distro`: install the configured OVN and OVS packages through a supported
  DNF- or APT-based package manager.
- `package`: install local RPM or DEB files supplied directly or found in a
  directory.
- `source`: build and install the source tree already present at
  `ovn_install_source_dir`, including its OVS submodule.
- `git`: clone `ovn_install_git_repo` at `ovn_install_git_version`, then perform
  a source build.
- `artifact`: validate and unpack a compatible artifact produced by the
  `ovn_artifact` role.

The main distro and package settings are:

- `ovn_install_distro_version`: `latest` requests the latest packages; any
  other value ensures the configured packages are present. It does not pin an
  arbitrary package version.
- `ovn_install_distro_package_names` and
  `ovn_install_distro_repository_package_names`: package and optional repository
  package mappings for each package manager.
- `ovn_install_package_files`: local package paths, supplied as a list or a
  YAML-encoded list.
- `ovn_install_package_dir`: directory searched for RPM and DEB files when no
  explicit files are supplied.

The main source and Git settings are:

- `ovn_install_source_dir`: source checkout to build or destination for a Git
  clone.
- `ovn_install_git_repo`: repository cloned by the `git` method.
- `ovn_install_git_version`: branch, tag, or commit to clone. It defaults to
  `ovn_install_git_branch`.
- `ovn_install_cc`: compiler command. A non-default compiler is installed
  through the host package manager.
- `ovn_install_configure_flags` and `ovn_install_make_flags`: additional OVN
  configure and make arguments.
- `ovn_install_werror`: enable warnings as errors for both OVN and OVS.
- `ovn_install_destdir`: optional staging root passed to `make install`.
- `ovn_install_dpdk_enabled`: build a DPDK-enabled `ovs-vswitchd`.
- `ovn_install_dpdk_dir`: existing DPDK installation used by that build.

Build dependencies, Git packages, DPDK runtime packages, and repository
packages can be overridden with the package-manager mappings in
`defaults/main.yml`.

For artifact installation, configure the artifact name and cache through the
`ovn_artifact_*` variables. The artifact must match the target distribution,
distribution version, architecture, and build settings. An exact source
revision can also be required.

If automatic path detection is unsuitable, set
`ovn_install_ovn_ctl_path`, `ovn_install_nb_control_socket`, and
`ovn_install_sb_control_socket` explicitly. See `defaults/main.yml` for all
default values.

## Usage

Install the distribution packages:

```yaml
ovn_install_method: distro
ovn_install_distro_version: latest
```

Build a specific Git revision with Clang and warnings as errors:

```yaml
ovn_install_method: git
ovn_install_git_repo: https://github.com/ovn-org/ovn.git
ovn_install_git_version: main
ovn_install_cc: clang
ovn_install_werror: true
ovn_install_configure_flags: --enable-ssl
```

Install compatible files already created by the `ovn_artifact` role:

```yaml
ovn_install_method: artifact
ovn_artifact_name: ovn-fedora
ovn_artifact_cache_dir: /var/tmp/ovn-artifacts
ovn_artifact_expected_revision: 0123456789abcdef
```
