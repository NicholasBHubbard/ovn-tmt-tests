import json
from typing import Any, Optional


def _decode(value: Any) -> Any:
    if not isinstance(value, list) or len(value) != 2:
        return value

    kind, contents = value
    if kind in {"uuid", "named-uuid"}:
        return contents
    if kind == "set":
        return [_decode(item) for item in contents]
    if kind == "map":
        return {_decode(key): _decode(item) for key, item in contents}
    return value


class Ovsdb:
    def __init__(self, runner: Any, command: str, guest: Optional[str] = None) -> None:
        self.runner = runner
        self.command = command
        self.guest = guest

    def find(
        self, table: str, *conditions: str, columns: tuple[str, ...]
    ) -> list[dict[str, Any]]:
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
    ) -> dict[str, Any]:
        rows = self.find(table, *conditions, columns=columns)
        if len(rows) != 1:
            raise LookupError(f"expected one {table} row, found {len(rows)}")
        return rows[0]

    def by_name(self, table: str, name: str, *columns: str) -> dict[str, Any]:
        return self.one(table, f"name={json.dumps(name)}", columns=columns)

    def managed(self, table: str, identifier: str, *columns: str) -> dict[str, Any]:
        return self.one(
            table,
            f"external_ids:ovn-tmt-tests-id={json.dumps(identifier)}",
            columns=columns,
        )

    def value(self, table: str, column: str, *conditions: str) -> Any:
        return self.one(table, *conditions, columns=(column,))[column]

    def values(self, table: str, column: str, *conditions: str) -> list[Any]:
        return [row[column] for row in self.find(table, *conditions, columns=(column,))]

    def referring_names(self, table: str, column: str, uuid: str) -> list[str]:
        return self.values(table, "name", f"{column}{{>=}}{uuid}")

    def exists(self, table: str, *conditions: str) -> bool:
        return bool(self.find(table, *conditions, columns=("_uuid",)))
