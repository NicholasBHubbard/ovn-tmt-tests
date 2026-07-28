import json


def _decode(value):
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
    def __init__(self, runner, command, guest=None):
        self.runner = runner
        self.command = command
        self.guest = guest

    def find(self, table, *conditions, columns):
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
        return [
            {
                heading: _decode(value)
                for heading, value in zip(headings, row, strict=True)
            }
            for row in result["data"]
        ]

    def one(self, table, *conditions, columns):
        rows = self.find(table, *conditions, columns=columns)
        if len(rows) != 1:
            raise LookupError(f"expected one {table} row, found {len(rows)}")
        return rows[0]

    def by_name(self, table, name, *columns):
        return self.one(table, f"name={json.dumps(name)}", columns=columns)

    def managed(self, table, identifier, *columns):
        return self.one(
            table,
            f"external_ids:ovn-tmt-tests-id={json.dumps(identifier)}",
            columns=columns,
        )

    def value(self, table, column, *conditions):
        return self.one(table, *conditions, columns=(column,))[column]

    def values(self, table, column, *conditions):
        return [row[column] for row in self.find(table, *conditions, columns=(column,))]

    def referring_names(self, table, column, uuid):
        return self.values(table, "name", f"{column}{{>=}}{uuid}")

    def exists(self, table, *conditions):
        return bool(self.find(table, *conditions, columns=("_uuid",)))
