# ovs_external_ids

## Purpose

Set or remove host-wide Open vSwitch external IDs. These values are stored in
the singleton `Open_vSwitch` database row and provide metadata or configuration
to OVS and related systems, such as OVN bridge mappings.

The role manages only the keys listed in `ovs_external_ids`. Unlisted external
IDs are left unchanged. Open vSwitch must already be installed, initialized,
and running.

## Configuration

Set `ovs_external_ids` to a mapping of external-ID keys to values. Keys must be
nonempty strings. A string value sets or updates the key, while `null` removes
it. The mapping defaults to empty, which makes no changes.

The complete mapping is validated before OVS is changed. All necessary updates
are applied atomically, unlisted keys remain untouched, and identical
reapplication reports no change. See `defaults/main.yml` for the default value.

## Usage

Configure an OVN bridge mapping and a chassis identifier:

```yaml
ovs_external_ids:
  ovn-bridge-mappings: public:br-ex
  system-id: chassis-1
```

Remove one external ID without changing any others:

```yaml
ovs_external_ids:
  ovn-bridge-mappings: null
```
