# ovs_tunnel_mesh

## Purpose

Create Open vSwitch tunnel meshes between inventory hosts. A mesh can connect
every host directly to every other host, or connect the hosts through a single
hub. Open vSwitch must already be installed and running on each participating
host.

The role creates the requested bridge and manages the tunnel ports belonging to
each listed mesh. Ports are identified by OVS external IDs so stale ports can be
removed when that mesh is reconfigured.

## Configuration

Set `ovs_tunnel_mesh_definitions` to a list of mesh definitions. Each definition
accepts:

- `name`: a name identifying the managed mesh.
- `hosts`: at least two inventory host names.
- `bridge`: the OVS bridge used by the mesh.
- `key`: a tunnel key that should be unique to the mesh.
- `type`: `geneve`, `gre`, or `vxlan`; the default is `geneve`.
- `hub`: an optional member of `hosts` that changes the full mesh into a
  hub-and-spoke topology.
- `addresses`: an optional mapping from host names to literal tunnel endpoint
  IP addresses. Otherwise, each peer's `ansible_host` value is used and must
  also be a literal IP address.
- `state`: `present` by default, or `absent` to remove the mesh's managed tunnel
  ports.

Each listed definition is authoritative for its own managed ports. To remove a
mesh, apply its definition with `state: absent`; simply omitting the definition
does not identify which existing mesh should be removed. The role does not
remove the mesh bridge. Every host in a present mesh must be inside the play's
execution scope; the scope may contain additional hosts so stale ports can be
removed after membership changes. Identical reapplication reports no change.
The list defaults to empty. See `defaults/main.yml` for the default value.

## Usage

Create a full Geneve mesh between three hosts:

```yaml
ovs_tunnel_mesh_definitions:
  - name: test-overlay
    hosts:
      - compute-1
      - compute-2
      - compute-3
    bridge: br-overlay
    key: 100
```

Use the same hosts in a hub-and-spoke VXLAN topology with explicit tunnel
addresses:

```yaml
ovs_tunnel_mesh_definitions:
  - name: test-overlay
    hosts:
      - compute-1
      - compute-2
      - compute-3
    hub: compute-1
    bridge: br-overlay
    type: vxlan
    key: 100
    addresses:
      compute-1: 192.0.2.11
      compute-2: 192.0.2.12
      compute-3: 192.0.2.13
```
