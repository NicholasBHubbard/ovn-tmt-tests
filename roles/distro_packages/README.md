# distro_packages

## Purpose

Install distribution-specific packages through one interface. The role supports
APT, DNF-compatible package managers, and Homebrew, and selects the appropriate
package names from the detected host.

## Configuration

The role accepts these `distro_packages_*` variables:

- `distro_packages_names`: required package list, or a mapping with `apt`, `dnf`,
  and `brew` package lists.
- `distro_packages_repository_names`: optional repository-enabling packages to
  install before the main APT or DNF package list. It accepts the same list or
  mapping forms.
- `distro_packages_state`: requested state for the main packages.
- `distro_packages_update_cache`: whether APT updates its package cache.

See `defaults/main.yml` for the default values.

## Usage

```yaml
- name: Install build tools
  ansible.builtin.include_role:
    name: distro_packages
  vars:
    distro_packages_names:
      apt:
        - build-essential
      dnf:
        - make
        - gcc
      brew:
        - make
        - gcc
```
