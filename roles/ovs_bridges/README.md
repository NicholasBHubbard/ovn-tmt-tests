# ovs_bridges

## Purpose

Create and remove Open vSwitch bridges. An OVS bridge provides a Layer 2
switching domain to which physical interfaces, tunnels, and test endpoints can
be attached.

The role manages only the bridges listed in `ovs_bridges`. Unlisted bridges are
left unchanged. Open vSwitch must already be installed and running.

## Configuration

Set `ovs_bridges` to a list of bridge names or bridge definitions:

- A string creates a bridge with that name.
- A mapping accepts a required `name` and an optional `state`.
- `state` is `present` by default, or `absent` to remove the bridge.

Bridge names must be unique within the list. The role validates the complete
configuration before changing OVS, and identical reapplication reports no
change. Removing a bridge also removes its attached OVS ports. See
`defaults/main.yml` for the default value.

## Usage

Create two OVS bridges:

```yaml
ovs_bridges:
  - br-int
  - name: br-provider
```

Remove one bridge without changing other OVS bridges:

```yaml
ovs_bridges:
  - name: br-provider
    state: absent
```
