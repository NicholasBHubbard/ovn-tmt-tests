from pathlib import Path

import yaml
from ovn_test.topology import Topology

from ._support import topology_data


def test_topology_loads_guests_and_roles(tmp_path: Path) -> None:
    path = tmp_path / "topology.yaml"
    path.write_text(yaml.safe_dump(topology_data()))

    topology = Topology.from_file(path)

    assert topology.current == "central"
    assert topology.role("compute") == ["compute-1", "compute-2"]
    assert topology.hostname("compute-1") == "192.0.2.2"
    assert topology.is_local("central")
    assert not topology.is_local("compute-1")
