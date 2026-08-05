# kube_burner

## Purpose

Install `kube-burner-ocp` from an upstream release because it is not available
in distribution repositories. The role selects the release for the Linux or
macOS host, verifies its checksum, and installs the executable in `PATH`.

## Configuration

The role accepts these `kube_burner_*` variables:

With no overrides, the role installs the pinned version from `defaults/main.yml`.
When selecting another version, its checksum manifest is found automatically.

- `kube_burner_version`: release version to install.
- `kube_burner_install_dir`: destination directory for the executable.
- `kube_burner_cache_dir`: directory for downloaded and extracted files.
- `kube_burner_release_base_url`: base URL containing versioned releases.
- `kube_burner_verify_checksum`: whether to verify the archive checksum.
- `kube_burner_checksum_url`: optional checksum-manifest URL override.
- `kube_burner_checksum`: optional SHA-256 digest override.

See `defaults/main.yml` for the default values.

## Usage

```yaml
- name: Install kube-burner-ocp
  hosts: all
  become: true
  roles:
    - kube_burner
```
