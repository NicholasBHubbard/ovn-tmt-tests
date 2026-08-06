from pathlib import Path
from typing import Any, Callable

import pytest
import yaml
from ovn_test.topology import Topology


def test_topology_preserves_tmt_order_and_resolves_guests(topology: Topology) -> None:
    assert topology.current == "central"
    assert topology.guests() == ["compute-1", "central", "compute-2"]
    assert topology.roles() == ["compute", "central"]
    assert topology.role("compute") == ["compute-1", "compute-2"]
    assert topology.hostname("compute-1") == "192.0.2.2"
    assert topology.is_local("central")
    assert not topology.is_local("compute-1")


def test_topology_owns_its_data(topology: Topology) -> None:
    data = topology.to_dict()
    loaded = Topology(data)
    data["guest"]["name"] = "compute-1"
    exported = loaded.to_dict()
    exported["guests"]["compute-1"]["hostname"] = "changed"

    assert loaded.current == "central"
    assert loaded.hostname("compute-1") == "192.0.2.2"


def test_topology_loads_files_and_explicit_environment(
    tmp_path: Path, topology: Topology
) -> None:
    path = tmp_path / "topology.yaml"
    path.write_text(yaml.safe_dump(topology.to_dict()))

    loaded = Topology.from_environment({"TMT_TOPOLOGY_YAML": str(path)})

    assert loaded.guests() == topology.guests()


def test_topology_uses_process_environment(
    tmp_path: Path, topology: Topology, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "topology.yaml"
    path.write_text(yaml.safe_dump(topology.to_dict()))
    monkeypatch.setenv("TMT_TOPOLOGY_YAML", str(path))

    assert Topology.from_environment().current == "central"


@pytest.mark.parametrize("environment", ({}, {"TMT_TOPOLOGY_YAML": ""}))
def test_topology_requires_an_environment_path(
    environment: dict[str, str],
) -> None:
    with pytest.raises(ValueError, match="TMT_TOPOLOGY_YAML must be set"):
        Topology.from_environment(environment)


@pytest.mark.parametrize(
    "change",
    (
        lambda data: data.pop("guest"),
        lambda data: data["guest-names"].append("central"),
        lambda data: data["guests"]["compute-1"].update(hostname=""),
        lambda data: data["roles"]["compute"].append("missing"),
        lambda data: data["guests"]["compute-1"].update(role="central"),
        lambda data: data["guest"].update(name="missing"),
    ),
)
def test_topology_rejects_inconsistent_schema(
    topology: Topology, change: Callable[[dict[str, Any]], object]
) -> None:
    data = topology.to_dict()
    change(data)

    with pytest.raises(ValueError, match="invalid tmt topology"):
        Topology(data)


@pytest.mark.parametrize("data", (None, [], "topology"))
def test_topology_rejects_non_mapping_schema(data: Any) -> None:
    with pytest.raises(ValueError, match="expected a mapping"):
        Topology(data)


def test_topology_rejects_invalid_yaml(tmp_path: Path) -> None:
    path = tmp_path / "topology.yaml"
    path.write_text("guest: [")

    with pytest.raises(ValueError, match="invalid tmt topology YAML"):
        Topology.from_file(path)


def test_topology_rejects_unknown_roles_and_guests(topology: Topology) -> None:
    with pytest.raises(KeyError, match="unknown topology role"):
        topology.role("missing")
    with pytest.raises(KeyError, match="unknown topology guest"):
        topology.hostname("missing")
    with pytest.raises(KeyError, match="unknown topology guest"):
        topology.is_local("missing")


def test_topology_accepts_a_local_guest_without_a_hostname(topology: Topology) -> None:
    data = topology.to_dict()
    data["guest"]["hostname"] = None
    data["guests"]["central"]["hostname"] = None
    local = Topology(data)

    assert local.is_local("central")
    with pytest.raises(ValueError, match="has no hostname"):
        local.hostname("central")
