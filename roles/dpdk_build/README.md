# dpdk_build

## Purpose

Build and install the Data Plane Development Kit (DPDK) from an official source
release. This is used when an OVS or OVN build needs DPDK support. The role
supports DNF- and APT-based Linux systems; DPDK is not supported on macOS.

## Configuration

The role accepts these `dpdk_build_*` variables:

- `dpdk_build_version`: DPDK release version to download and build.
- `dpdk_build_checksum`: checksum used to verify the downloaded source archive.
  The version and checksum must be updated together.
- `dpdk_build_install_dir`: directory where DPDK is installed.
- `dpdk_build_drivers`: comma-separated DPDK drivers to enable.
- `dpdk_build_source_dir`: directory where the source is extracted and built.
- `dpdk_build_dependency_package_names`: build dependencies for each supported
  package manager.

See `defaults/main.yml` for the default values.

## Usage

```yaml
- name: Build DPDK
  hosts: all
  become: true
  roles:
    - role: dpdk_build
      vars:
        dpdk_build_drivers: "net/null,net/tap"
```
