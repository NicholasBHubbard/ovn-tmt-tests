# ovn_artifact

## Purpose

Build OVN and OVS once for reuse on compatible test guests. The role creates a
compressed installation artifact, records its source revision, build settings,
operating-system identity, architecture, and checksum in a manifest, then
fetches both files to the machine running tmt.

Before an artifact is installed, the role verifies that its manifest matches
the requested build and target system. Artifacts are only compatible with the
same distribution, distribution version, and architecture.

## Configuration

The main `ovn_artifact_*` variables are:

- `ovn_artifact_action`: `build` to create or reuse an artifact, or `validate`
  to inspect an existing artifact without changing the target guest.
- `ovn_artifact_build`: whether to build a new artifact. Set this to `false` to
  reuse files already in the cache.
- `ovn_artifact_name`: name used for the artifact and manifest files.
- `ovn_artifact_cache_dir`: directory holding artifacts on the machine running
  tmt. It defaults to the Ansible inventory directory.
- `ovn_artifact_expected_revision`: exact OVN Git revision required when
  reusing an artifact.
- `ovn_artifact_staging_dir`: temporary installation root on the builder.
- `ovn_artifact_archive_package_names`: archive-tool packages for each supported
  package manager.
- `ovn_artifact_local_path` and `ovn_artifact_manifest_local_path`: optional
  overrides for the cached files.
- `ovn_artifact_expected_distribution`,
  `ovn_artifact_expected_distribution_version`, and
  `ovn_artifact_expected_architecture`: target identity used during validation.

The build itself uses the `ovn_install_*` configuration, including the source,
compiler, build flags, `-Werror`, and optional DPDK settings. These values become
part of the artifact identity and must also match when it is installed.

See `defaults/main.yml` for all paths and default values.

## Usage

The role is normally applied to one builder guest by the larger artifact-build
workflow:

```yaml
- name: Build OVN source artifact
  hosts: central
  become: true
  roles:
    - role: ovn_artifact
      ovn_artifact_action: build
      ovn_artifact_name: ovn-fedora
      ovn_artifact_cache_dir: /var/tmp/ovn-artifacts
```

The `ovn_install` role installs the resulting artifact on compatible guests
when configured with `ovn_install_method: artifact`.
