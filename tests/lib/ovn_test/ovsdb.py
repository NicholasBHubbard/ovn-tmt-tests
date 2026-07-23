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

    def value(self, table, column, *conditions):
        return self.one(table, *conditions, columns=(column,))[column]

    def exists(self, table, *conditions):
        return bool(self.find(table, *conditions, columns=("_uuid",)))
