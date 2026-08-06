import runpy
from pathlib import Path
from typing import Any

import pytest


def np_labels_config(mode: str = "small") -> dict[str, Any]:
    return {
        "mode": mode,
        "namespaces": 2,
        "pods_per_namespace": 16,
        "labels": 4,
        "base_pods": 2,
        "protocols": ["tcp", "udp", "sctp"],
        "timeout": 60,
        "sync_timeout": 1800,
        "ipv4": True,
        "ipv6": False,
        "mtu": 1342,
        "workers": 2,
        "chassis": 2,
        "deny_priority": 1,
        "control_priority": 2,
        "allow_priority": 3,
    }


@pytest.mark.parametrize("mode", ("small", "large"))
def test_np_labels_reproduces_original_workload_shape(tree: Path, mode: str) -> None:
    workload = runpy.run_path(str(tree / "tests/ovn-scale-testing/np-labels/test.py"))
    config = np_labels_config(mode)

    workload["validate_config"](config)
    groups = workload["label_groups"](config["total_pods"], config["labels"])

    assert config["total_pods"] == 32
    assert groups[0] == list(range(0, 32, 4))
    assert workload["local_label_index"](1, 2, 16, 4) == 18
    target = workload["target_indexes"](mode, 0, 0, 16, groups)
    if mode == "small":
        assert target == [2, 3, 6, 7, 10, 11, 14, 15]
    else:
        assert target == groups[1]


@pytest.mark.parametrize(
    ("name", "value"),
    (
        ("mode", "invalid"),
        ("namespaces", 0),
        ("pods_per_namespace", 3),
        ("labels", 2),
        ("base_pods", -1),
        ("protocols", []),
        ("ipv4", False),
        ("mtu", 575),
        ("allow_priority", 1),
    ),
)
def test_np_labels_rejects_invalid_configuration(
    tree: Path,
    name: str,
    value: Any,
) -> None:
    workload = runpy.run_path(str(tree / "tests/ovn-scale-testing/np-labels/test.py"))
    config = np_labels_config()
    config[name] = value

    with pytest.raises(ValueError, match=r".+"):
        workload["validate_config"](config)
