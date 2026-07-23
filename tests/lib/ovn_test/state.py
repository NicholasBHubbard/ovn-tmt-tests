import os
from pathlib import Path


class Snapshots:
    def __init__(self, root):
        self.root = Path(root)

    @classmethod
    def from_environment(cls, environment=None):
        environment = os.environ if environment is None else environment
        return cls(Path(environment["TMT_TEST_DATA"]) / "snapshots")

    def path(self, name):
        path = self.root / name
        if path.parent != self.root or not name:
            raise ValueError("snapshot name must be a single path component")
        return path

    def save(self, name, value):
        value = str(value)
        self.root.mkdir(parents=True, exist_ok=True)
        self.path(name).write_text(value)
        return value

    def load(self, name):
        return self.path(name).read_text()
