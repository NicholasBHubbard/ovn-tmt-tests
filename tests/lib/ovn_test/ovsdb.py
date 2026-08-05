import json
import re
from typing import Any, Optional, Protocol
from uuid import UUID

_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
_MANAGED_ID = "ovn-tmt-tests-id"


class _OutputRunner(Protocol):
    def output(self, *command: object, guest: Optional[str] = None) -> str: ...


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} must be a nonempty string")
    return value


def _identifier(value: object, label: str) -> str:
    value = _text(value, label)
    if not _IDENTIFIER.fullmatch(value):
        raise ValueError(f"invalid OVSDB {label}: {value!r}")
    return value


def _ovs_string(value: object, label: str) -> str:
    value = _text(value, label)
    if "\0" in value:
        raise ValueError(f"{label} cannot contain a null byte")
    return value


def _uuid(value: object) -> str:
    value = _text(value, "UUID")
    try:
        parsed = str(UUID(value))
    except ValueError as error:
        raise ValueError(f"invalid OVSDB UUID: {value!r}") from error
    if value != parsed:
        raise ValueError(f"invalid OVSDB UUID: {value!r}")
    return value


def _atom(value: Any) -> Any:
    decoded = _decode(value)
    if isinstance(decoded, (dict, list)):
        raise RuntimeError("invalid nested OVSDB collection")
    return decoded


def _decode(value: Any) -> Any:
    if value is None or isinstance(value, dict):
        raise RuntimeError("invalid OVSDB value")
    if not isinstance(value, list):
        return value
    if len(value) != 2 or not isinstance(value[0], str):
        raise RuntimeError("invalid OVSDB tagged value")

    kind, contents = value
    if kind == "uuid":
        try:
            return _uuid(contents)
        except ValueError as error:
            raise RuntimeError("invalid OVSDB UUID value") from error
    if kind == "named-uuid":
        if not isinstance(contents, str) or not contents:
            raise RuntimeError("invalid OVSDB named UUID value")
        return contents
    if kind == "set":
        if not isinstance(contents, list):
            raise RuntimeError("invalid OVSDB set value")
        decoded = [_atom(item) for item in contents]
        if len(decoded) != len(set(decoded)):
            raise RuntimeError("duplicate value in OVSDB set")
        return decoded
    if kind == "map":
        if not isinstance(contents, list):
            raise RuntimeError("invalid OVSDB map value")
        decoded = {}
        for pair in contents:
            if not isinstance(pair, list) or len(pair) != 2:
                raise RuntimeError("invalid OVSDB map entry")
            key = _atom(pair[0])
            item = _atom(pair[1])
            if key in decoded:
                raise RuntimeError("duplicate key in OVSDB map")
            decoded[key] = item
        return decoded
    raise RuntimeError(f"unknown OVSDB value tag: {kind!r}")


class Ovsdb:
    def __init__(
        self, runner: _OutputRunner, command: str, guest: Optional[str] = None
    ) -> None:
        self.runner = runner
        self.command = _text(command, "command")
        self.guest = None if guest is None else _text(guest, "guest")

    def find(
        self, table: str, *conditions: str, columns: tuple[str, ...]
    ) -> list[dict[str, Any]]:
        table = _identifier(table, "table")
        if not columns:
            raise ValueError("at least one OVSDB column is required")
        columns = tuple(_identifier(column, "column") for column in columns)
        if len(set(columns)) != len(columns):
            raise ValueError("OVSDB columns must be unique")
        conditions = tuple(_text(condition, "condition") for condition in conditions)

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
        try:
            result = json.loads(output)
        except (json.JSONDecodeError, TypeError) as error:
            raise RuntimeError("invalid JSON from OVSDB command") from error
        if not isinstance(result, dict):
            raise RuntimeError("OVSDB response must be an object")

        headings = result.get("headings")
        rows = result.get("data")
        if (
            not isinstance(headings, list)
            or not all(isinstance(heading, str) for heading in headings)
            or len(headings) != len(set(headings))
        ):
            raise RuntimeError("invalid OVSDB response headings")
        headings = [str(heading) for heading in headings]
        if len(headings) != len(columns) or set(headings) != set(columns):
            raise RuntimeError("OVSDB response headings do not match requested columns")
        if not isinstance(rows, list):
            raise RuntimeError("invalid OVSDB response data")

        decoded = []
        for row in rows:
            if not isinstance(row, list) or len(row) != len(headings):
                raise RuntimeError("OVSDB row does not match its headings")
            decoded.append(
                {heading: _decode(value) for heading, value in zip(headings, row)}
            )
        return decoded

    def one(
        self, table: str, *conditions: str, columns: tuple[str, ...]
    ) -> dict[str, Any]:
        rows = self.find(table, *conditions, columns=columns)
        if len(rows) != 1:
            raise LookupError(f"expected one {table} row, found {len(rows)}")
        return rows[0]

    def by_name(self, table: str, name: str, *columns: str) -> dict[str, Any]:
        name = _ovs_string(name, "name")
        return self.one(table, f"name={json.dumps(name)}", columns=columns)

    def by_external_id(
        self, table: str, key: str, value: str, *columns: str
    ) -> dict[str, Any]:
        key = _ovs_string(key, "external ID key")
        value = _ovs_string(value, "external ID value")
        return self.one(
            table,
            f"external_ids:{json.dumps(key)}={json.dumps(value)}",
            columns=columns,
        )

    def by_id(self, table: str, identifier: str, *columns: str) -> dict[str, Any]:
        return self.by_external_id(table, _MANAGED_ID, identifier, *columns)

    def value(self, table: str, column: str, *conditions: str) -> Any:
        return self.one(table, *conditions, columns=(column,))[column]

    def values(self, table: str, column: str, *conditions: str) -> list[Any]:
        return [row[column] for row in self.find(table, *conditions, columns=(column,))]

    def referring_names(self, table: str, column: str, uuid: str) -> list[str]:
        return self.values(table, "name", f"{column}{{>=}}{_uuid(uuid)}")

    def exists(self, table: str, *conditions: str) -> bool:
        return bool(self.find(table, *conditions, columns=("_uuid",)))
