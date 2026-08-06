import json
from collections.abc import Callable
from typing import Any, Optional

import pytest
from ovn_test.ovsdb import Ovsdb

UUID_1 = "00000000-0000-0000-0000-000000000001"
UUID_2 = "00000000-0000-0000-0000-000000000002"


class FakeRunner:
    def __init__(self, response: str) -> None:
        self.response = response
        self.calls = []

    def output(self, *command: object, guest: Optional[str] = None) -> str:
        self.calls.append((command, guest))
        return self.response


def response(headings: Any, data: Any) -> str:
    return json.dumps({"headings": headings, "data": data})


def test_find_builds_query_and_decodes_rows() -> None:
    runner = FakeRunner(
        response(
            ["_uuid", "name", "ports", "options"],
            [
                [
                    ["uuid", UUID_1],
                    "switch-1",
                    ["set", [["uuid", UUID_1], ["uuid", UUID_2]]],
                    ["map", [["mode", "secure"], ["enabled", True]]],
                ]
            ],
        )
    )

    rows = Ovsdb(runner, "ovn-nbctl", "central").find(
        "Logical_Switch",
        "name=switch-1",
        columns=("name", "ports", "options", "_uuid"),
    )

    assert rows == [
        {
            "_uuid": UUID_1,
            "name": "switch-1",
            "ports": [UUID_1, UUID_2],
            "options": {"mode": "secure", "enabled": True},
        }
    ]
    assert runner.calls == [
        (
            (
                "ovn-nbctl",
                "--format=json",
                "--data=json",
                "--columns=name,ports,options,_uuid",
                "find",
                "Logical_Switch",
                "name=switch-1",
            ),
            "central",
        )
    ]


@pytest.mark.parametrize(
    "payload",
    (
        "not JSON",
        json.dumps([]),
        json.dumps({}),
        response("name", []),
        response(["name", "name"], []),
        response(["other"], []),
        response(["name"], {}),
        response(["name"], ["row"]),
        response(["name"], [[]]),
    ),
)
def test_find_rejects_malformed_responses(payload: str) -> None:
    with pytest.raises(RuntimeError):
        Ovsdb(FakeRunner(payload), "ovn-nbctl").find(
            "Logical_Switch", columns=("name",)
        )


@pytest.mark.parametrize(
    "value",
    (
        None,
        {},
        [],
        ["unknown", []],
        ["uuid", "not-a-uuid"],
        ["named-uuid", ""],
        ["set", "not-a-list"],
        ["set", ["duplicate", "duplicate"]],
        ["set", [["set", []]]],
        ["map", "not-a-list"],
        ["map", [["key"]]],
        ["map", [["key", "one"], ["key", "two"]]],
        ["map", [["key", ["set", []]]]],
    ),
)
def test_find_rejects_malformed_values(value: Any) -> None:
    with pytest.raises(RuntimeError):
        Ovsdb(FakeRunner(response(["value"], [[value]])), "ovn-nbctl").find(
            "Logical_Switch", columns=("value",)
        )


@pytest.mark.parametrize(
    "operation",
    (
        lambda runner: Ovsdb(runner, ""),
        lambda runner: Ovsdb(runner, "ovn-nbctl", ""),
        lambda runner: Ovsdb(runner, "ovn-nbctl").find("", columns=("name",)),
        lambda runner: Ovsdb(runner, "ovn-nbctl").find("bad-table", columns=("name",)),
        lambda runner: Ovsdb(runner, "ovn-nbctl").find("Logical_Switch", columns=()),
        lambda runner: Ovsdb(runner, "ovn-nbctl").find(
            "Logical_Switch", columns=("name", "name")
        ),
        lambda runner: Ovsdb(runner, "ovn-nbctl").find(
            "Logical_Switch", columns=("bad-column",)
        ),
        lambda runner: Ovsdb(runner, "ovn-nbctl").find(
            "Logical_Switch", "", columns=("name",)
        ),
        lambda runner: Ovsdb(runner, "ovn-nbctl").by_name("Logical_Switch", "", "name"),
        lambda runner: Ovsdb(runner, "ovn-nbctl").by_external_id(
            "Logical_Switch", "bad\0key", "value", "name"
        ),
        lambda runner: Ovsdb(runner, "ovn-nbctl").by_external_id(
            "Logical_Switch", "", "value", "name"
        ),
        lambda runner: Ovsdb(runner, "ovn-nbctl").by_external_id(
            "Logical_Switch", "key", "", "name"
        ),
        lambda runner: Ovsdb(runner, "ovn-nbctl").by_id("Logical_Switch", "", "name"),
        lambda runner: Ovsdb(runner, "ovn-nbctl").referring_names(
            "Logical_Switch", "ports", "not-a-uuid"
        ),
    ),
)
def test_queries_reject_invalid_inputs(
    operation: Callable[[FakeRunner], object],
) -> None:
    runner = FakeRunner(response(["name"], []))

    with pytest.raises(ValueError, match=r".+"):
        operation(runner)

    assert not runner.calls


def test_query_conveniences_quote_values() -> None:
    runner = FakeRunner(response(["name"], [["switch-1"]]))
    database = Ovsdb(runner, "ovn-nbctl")

    assert database.by_name("Logical_Switch", 'switch"1', "name") == {
        "name": "switch-1"
    }
    assert database.by_external_id(
        "Logical_Switch", "owner/name", 'team"1', "name"
    ) == {"name": "switch-1"}
    assert database.by_id("Logical_Switch", "managed-1", "name") == {"name": "switch-1"}
    assert database.referring_names("Logical_Switch", "ports", UUID_1) == ["switch-1"]

    assert runner.calls[0][0][-1] == 'name="switch\\"1"'
    assert runner.calls[1][0][-1] == 'external_ids:"owner/name"="team\\"1"'
    assert runner.calls[2][0][-1] == ('external_ids:"ovn-tmt-tests-id"="managed-1"')
    assert runner.calls[3][0][-1] == f"ports{{>=}}{UUID_1}"


def test_value_conveniences_return_requested_columns() -> None:
    runner = FakeRunner(response(["name"], [["one"], ["two"]]))
    database = Ovsdb(runner, "ovn-nbctl")

    assert database.values("Logical_Switch", "name") == ["one", "two"]

    runner.response = response(["name"], [["one"]])
    assert database.value("Logical_Switch", "name", "name=one") == "one"


@pytest.mark.parametrize(
    ("encoded", "decoded"),
    (
        ("plain", "plain"),
        (["named-uuid", "temporary"], "temporary"),
        (["set", []], []),
        (["map", []], {}),
    ),
)
def test_find_decodes_valid_value_forms(encoded: Any, decoded: Any) -> None:
    database = Ovsdb(
        FakeRunner(response(["value"], [[encoded]])),
        "ovn-nbctl",
    )

    assert database.value("Logical_Switch", "value") == decoded


def test_one_and_exists_enforce_cardinality() -> None:
    empty = Ovsdb(FakeRunner(response(["name"], [])), "ovn-nbctl")
    multiple = Ovsdb(FakeRunner(response(["name"], [["one"], ["two"]])), "ovn-nbctl")

    with pytest.raises(LookupError, match="found 0"):
        empty.one("Logical_Switch", columns=("name",))
    with pytest.raises(LookupError, match="found 2"):
        multiple.one("Logical_Switch", columns=("name",))
    assert not Ovsdb(FakeRunner(response(["_uuid"], [])), "ovn-nbctl").exists(
        "Logical_Switch"
    )


def test_runner_failures_propagate() -> None:
    class FailingRunner:
        def output(self, *command: object, guest: Optional[str] = None) -> str:
            raise OSError("command failed")

    with pytest.raises(OSError, match="command failed"):
        Ovsdb(FailingRunner(), "ovn-nbctl").find("Logical_Switch", columns=("name",))


def test_ovsdb_decodes_json_rows() -> None:
    port_1 = "00000000-0000-0000-0000-000000000001"
    port_2 = "00000000-0000-0000-0000-000000000002"
    switch = "00000000-0000-0000-0000-000000000003"
    payload = {
        "headings": ["name", "ports", "external_ids", "_uuid"],
        "data": [
            [
                "sw0",
                ["set", [["uuid", port_1], ["uuid", port_2]]],
                ["map", [["owner", "test"], ["enabled", True]]],
                ["uuid", switch],
            ]
        ],
    }
    calls = []

    class FakeRunner:
        def output(self, *command: Any, **kwargs: Any) -> str:
            calls.append((command, kwargs))
            columns = command[3].removeprefix("--columns=").split(",")
            indexes = [payload["headings"].index(column) for column in columns]
            return json.dumps(
                {
                    "headings": columns,
                    "data": [
                        [row[index] for index in indexes]
                        if len(row) == len(payload["headings"])
                        else row
                        for row in payload["data"]
                    ],
                }
            )

    database = Ovsdb(FakeRunner(), "ovn-nbctl")

    rows = database.find(
        "Logical_Switch",
        "name=sw0",
        columns=("name", "ports", "external_ids", "_uuid"),
    )

    assert rows == [
        {
            "name": "sw0",
            "ports": [port_1, port_2],
            "external_ids": {"owner": "test", "enabled": True},
            "_uuid": switch,
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
    assert database.by_id("Logical_Switch", "managed:0", "name")["name"] == "sw0"
    assert database.referring_names("Logical_Switch", "ports", port_1) == ["sw0"]
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
    assert calls[5][0][-1] == 'external_ids:"ovn-tmt-tests-id"="managed:0"'
    assert calls[6][0][-1] == f"ports{{>=}}{port_1}"

    payload["data"] = [[]]
    with pytest.raises(RuntimeError, match="does not match"):
        database.find("Logical_Switch", columns=("name",))


def test_ovsdb_one_requires_exactly_one_row() -> None:
    class FakeRunner:
        def __init__(self, rows: Any) -> None:
            self.rows = rows

        def output(self, *command: Any, **kwargs: Any) -> str:
            column = command[3].removeprefix("--columns=")
            return json.dumps({"headings": [column], "data": self.rows})

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
