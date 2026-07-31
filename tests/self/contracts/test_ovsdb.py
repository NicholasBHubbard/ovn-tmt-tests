import json
from typing import Any

import pytest
from ovn_test.ovsdb import Ovsdb


def test_ovsdb_decodes_json_rows() -> None:
    payload = {
        "headings": ["name", "ports", "external_ids", "_uuid"],
        "data": [
            [
                "sw0",
                ["set", [["uuid", "port-1"], ["uuid", "port-2"]]],
                ["map", [["owner", "test"], ["enabled", True]]],
                ["uuid", "switch-1"],
            ]
        ],
    }
    calls = []

    class FakeRunner:
        def output(self, *command: Any, **kwargs: Any) -> str:
            calls.append((command, kwargs))
            return json.dumps(payload)

    database = Ovsdb(FakeRunner(), "ovn-nbctl")

    rows = database.find(
        "Logical_Switch",
        "name=sw0",
        columns=("name", "ports", "external_ids", "_uuid"),
    )

    assert rows == [
        {
            "name": "sw0",
            "ports": ["port-1", "port-2"],
            "external_ids": {"owner": "test", "enabled": True},
            "_uuid": "switch-1",
        }
    ]
    assert (
        database.one(
            "Logical_Switch",
            "name=sw0",
            columns=("name",),
        )["name"]
        == "sw0"
    )
    assert database.value("Logical_Switch", "name", "name=sw0") == "sw0"
    assert database.values("Logical_Switch", "name") == ["sw0"]
    assert database.by_name("Logical_Switch", 'sw"0', "name")["name"] == "sw0"
    assert database.managed("Logical_Switch", "managed:0", "name")["name"] == "sw0"
    assert database.referring_names("Logical_Switch", "ports", "port-1") == ["sw0"]
    assert database.exists("Logical_Switch", "name=sw0")
    assert calls[0][0] == (
        "ovn-nbctl",
        "--format=json",
        "--data=json",
        "--columns=name,ports,external_ids,_uuid",
        "find",
        "Logical_Switch",
        "name=sw0",
    )
    assert calls[4][0][-1] == 'name="sw\\"0"'
    assert calls[5][0][-1] == 'external_ids:ovn-tmt-tests-id="managed:0"'
    assert calls[6][0][-1] == "ports{>=}port-1"

    payload["data"] = [["sw0"]]
    with pytest.raises(ValueError, match="does not match"):
        database.find("Logical_Switch", columns=("name",))


def test_ovsdb_one_requires_exactly_one_row() -> None:
    class FakeRunner:
        def __init__(self, rows: Any) -> None:
            self.rows = rows

        def output(self, *command: Any, **kwargs: Any) -> str:
            return json.dumps({"headings": ["name"], "data": self.rows})

    with pytest.raises(LookupError, match="found 0"):
        Ovsdb(FakeRunner([]), "ovn-nbctl").one(
            "Logical_Switch", "name=missing", columns=("name",)
        )
    assert not Ovsdb(FakeRunner([]), "ovn-nbctl").exists(
        "Logical_Switch", "name=missing"
    )
    with pytest.raises(LookupError, match="found 2"):
        Ovsdb(FakeRunner([["one"], ["two"]]), "ovn-nbctl").one(
            "Logical_Switch", columns=("name",)
        )
