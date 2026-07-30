import json
from collections.abc import Mapping
from typing import Optional, cast

from ovn_test.command import Runner


def _decode(value: object) -> object:
    if not isinstance(value, list) or len(value) != 2:
        return value

    kind, contents = value
    if not isinstance(kind, str):
        return value
    if kind in {"uuid", "named-uuid"}:
        return contents
    if kind == "set" and isinstance(contents, list):
        return [_decode(item) for item in contents]
    if kind == "map" and isinstance(contents, list):
        result = {}
        for pair in contents:
            if not isinstance(pair, list) or len(pair) != 2:
                return value
            key, item = pair
            result[_decode(key)] = _decode(item)
        return result
    return value


def _text(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{label} is not text")
    return value


class Ovsdb:
    def __init__(
        self, runner: Runner, command: str, guest: Optional[str] = None
    ) -> None:
        self.runner = runner
        self.command = command
        self.guest = guest

    def find(
        self, table: str, *conditions: str, columns: tuple[str, ...]
    ) -> list[dict[str, object]]:
        output = self.runner.output(
            self.command,
            "--format=json",
            "--data=json",
            f"--columns={','.join(columns)}",
            "find",
            table,
            *conditions,
            guest=self.guest,
        )
        result = json.loads(output)
        headings = result["headings"]
        rows = result["data"]
        if any(len(row) != len(headings) for row in rows):
            raise ValueError("OVSDB row does not match its headings")
        return [
            {heading: _decode(value) for heading, value in zip(headings, row)}
            for row in rows
        ]

    def one(
        self, table: str, *conditions: str, columns: tuple[str, ...]
    ) -> dict[str, object]:
        rows = self.find(table, *conditions, columns=columns)
        if len(rows) != 1:
            raise LookupError(f"expected one {table} row, found {len(rows)}")
        return rows[0]

    def by_name(self, table: str, name: str, *columns: str) -> dict[str, object]:
        return self.one(table, f"name={json.dumps(name)}", columns=columns)

    def managed(self, table: str, identifier: str, *columns: str) -> dict[str, object]:
        return self.one(
            table,
            f"external_ids:ovn-tmt-tests-id={json.dumps(identifier)}",
            columns=columns,
        )

    def value(self, table: str, column: str, *conditions: str) -> object:
        return self.one(table, *conditions, columns=(column,))[column]

    def values(self, table: str, column: str, *conditions: str) -> list[object]:
        return [row[column] for row in self.find(table, *conditions, columns=(column,))]

    def mapping(self, table: str, column: str, *conditions: str) -> dict[str, object]:
        value = self.value(table, column, *conditions)
        if not isinstance(value, dict):
            raise TypeError(f"{table}.{column} is not a mapping")
        return {str(key): item for key, item in value.items()}

    @staticmethod
    def text(row: Mapping[str, object], column: str) -> str:
        return _text(row[column], column)

    @staticmethod
    def integer(row: Mapping[str, object], column: str) -> int:
        value = row[column]
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError(f"{column} is not an integer")
        return value

    @staticmethod
    def strings(row: Mapping[str, object], column: str) -> list[str]:
        value = row[column]
        if not isinstance(value, list) or not all(
            isinstance(item, str) for item in value
        ):
            raise TypeError(f"{column} is not a list of text")
        return cast(list[str], value)

    @staticmethod
    def row_mapping(row: Mapping[str, object], column: str) -> dict[str, object]:
        value = row[column]
        if not isinstance(value, dict):
            raise TypeError(f"{column} is not a mapping")
        return {str(key): item for key, item in value.items()}

    def referring_names(self, table: str, column: str, uuid: object) -> list[str]:
        uuid = _text(uuid, "OVSDB UUID")
        return [
            str(value) for value in self.values(table, "name", f"{column}{{>=}}{uuid}")
        ]

    def exists(self, table: str, *conditions: str) -> bool:
        return bool(self.find(table, *conditions, columns=("_uuid",)))
