import json
from pathlib import Path
from typing import Any, Optional
from unittest.mock import Mock

import ovn_test.scale
import pytest
from ovn_test.command import Runner
from ovn_test.scale import ScaleBaseline, verify_scale_environment
from ovn_test.topology import Topology


def external_ids_response(values: dict[str, str]) -> str:
    return json.dumps(
        {
            "headings": ["external_ids"],
            "data": [[["map", [[key, value] for key, value in values.items()]]]],
        }
    )


def test_scale_environment_honors_cluster_tls_ports_and_ipv6(
    topology: Topology, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = topology.to_dict()
    data["guests"]["central"]["hostname"] = "2001:db8::1"
    data["guest"]["hostname"] = "2001:db8::1"
    data["guests"]["central-2"] = {
        "name": "central-2",
        "hostname": "2001:db8::2",
        "role": "central-follower",
    }
    data["guest-names"].append("central-2")
    data["role-names"].append("central-follower")
    data["roles"]["central-follower"] = ["central-2"]
    topology = Topology(data)
    environment = {
        "OTT_CLUSTERED": "true",
        "OTT_SSL_ENABLED": "true",
        "OTT_MONITOR_ALL": "true",
        "OTT_NB_RAFT_PORT": "16643",
        "OTT_SB_PORT": "16642",
        "OTT_SB_RAFT_PORT": "16644",
    }
    remotes = "ssl:[2001:db8::1]:16642,ssl:[2001:db8::2]:16642"
    runner = Mock(spec=Runner)

    def output(*command: object, **options: object) -> str:
        if command[0] == "ovn-appctl":
            port = 16643 if command[-1] == "OVN_Northbound" else 16644
            return "Role: leader\n" + "\n".join(
                f"ssl:[2001:db8::{member}]:{port}" for member in (1, 2)
            )
        return external_ids_response({"ovn-remote": remotes, "ovn-monitor-all": "true"})

    runner.output.side_effect = output
    monkeypatch.setattr(
        ovn_test.scale,
        "ovsdb_control_socket",
        lambda runner, database, guest=None: f"/run/{database}.ctl",
    )

    assert verify_scale_environment(runner, topology, environment) == [
        "compute-1",
        "compute-2",
    ]
    assert runner.output.call_count == 6


@pytest.mark.parametrize(
    ("configured", "expected"),
    (
        (None, False),
        ("true", True),
    ),
)
def test_scale_environment_verifies_monitor_all_exactly(
    topology: Topology, configured: Optional[str], expected: bool
) -> None:
    external_ids = {"ovn-remote": "tcp:192.0.2.1:6642"}
    if configured is not None:
        external_ids["ovn-monitor-all"] = configured
    runner = Mock(spec=Runner)
    runner.output.return_value = external_ids_response(external_ids)

    assert verify_scale_environment(
        runner,
        topology,
        {"OTT_MONITOR_ALL": str(expected).lower()},
    ) == ["compute-1", "compute-2"]


def test_scale_environment_rejects_explicit_false_monitor_all(
    topology: Topology,
) -> None:
    runner = Mock(spec=Runner)
    runner.output.return_value = external_ids_response(
        {
            "ovn-remote": "tcp:192.0.2.1:6642",
            "ovn-monitor-all": "false",
        }
    )

    with pytest.raises(AssertionError):
        verify_scale_environment(runner, topology, {"OTT_MONITOR_ALL": "false"})


def test_scale_environment_propagates_ovsdb_failures(topology: Topology) -> None:
    runner = Mock(spec=Runner)
    runner.output.side_effect = OSError("OVSDB failed")

    with pytest.raises(OSError, match="OVSDB failed"):
        verify_scale_environment(runner, topology, {})


def test_scale_environment_rejects_invalid_external_ids(topology: Topology) -> None:
    runner = Mock(spec=Runner)
    runner.output.return_value = json.dumps(
        {"headings": ["external_ids"], "data": [["invalid"]]}
    )

    with pytest.raises(RuntimeError, match="external IDs"):
        verify_scale_environment(runner, topology, {})


def test_scale_environment_rejects_invalid_ports_before_querying_ovs(
    topology: Topology,
) -> None:
    runner = Mock(spec=Runner)

    with pytest.raises(ValueError, match="OTT_SB_PORT"):
        verify_scale_environment(runner, topology, {"OTT_SB_PORT": "0"})

    runner.output.assert_not_called()


@pytest.mark.parametrize(
    ("overrides", "message"),
    (
        ({"pods_per_worker": -1}, "pods per worker"),
        ({"pods_per_worker": True}, "pods per worker"),
        ({"protocols": []}, "non-empty sequence"),
        ({"protocols": "tcp"}, "must be a sequence"),
        ({"protocols": ["tcp", "tcp"]}, "unique"),
        ({"protocols": ["http"]}, "tcp, udp or sctp"),
        ({"sync_timeout": 0}, "sync timeout"),
    ),
)
def test_scale_baseline_rejects_invalid_configuration_before_creating_helpers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    overrides: dict[str, Any],
    message: str,
) -> None:
    external = Mock()
    workload = Mock()
    monkeypatch.setattr(ovn_test.scale, "ExternalPeers", external)
    monkeypatch.setattr(ovn_test.scale, "Workload", workload)
    options: dict[str, Any] = {
        "pods_per_worker": 1,
        "protocols": ["tcp"],
        "ipv4": True,
        "ipv6": False,
        "mtu": 1400,
        "timeout": 3,
        "sync_timeout": 10,
        "name": "baseline",
        "prefix": "base",
        **overrides,
    }

    with pytest.raises(ValueError, match=message):
        ScaleBaseline(Mock(spec=Runner), ["compute-1"], {}, tmp_path, **options)

    external.assert_not_called()
    workload.assert_not_called()


@pytest.mark.parametrize(
    ("operation", "action"),
    (
        ("cleanup", "cleanup"),
        ("verify_cleanup", "verify_cleanup"),
    ),
)
def test_scale_baseline_runs_all_cleanup_and_preserves_first_failure(
    operation: str, action: str
) -> None:
    first = RuntimeError("workload failed")
    baseline = object.__new__(ScaleBaseline)
    baseline.workload = Mock()
    baseline.external = Mock()
    getattr(baseline.workload, action).side_effect = first
    getattr(baseline.external, action).side_effect = RuntimeError("external failed")

    with pytest.raises(RuntimeError, match="workload failed") as error:
        getattr(baseline, operation)()

    assert error.value is first
    getattr(baseline.external, action).assert_called_once_with()
