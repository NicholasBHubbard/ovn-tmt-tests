import os
from collections.abc import Mapping
from pathlib import Path
from typing import Optional, Union


class Snapshots:
    def __init__(self, root: Union[str, os.PathLike[str]]) -> None:
        self.root = Path(root)

    @classmethod
    def from_environment(
        cls, environment: Optional[Mapping[str, str]] = None
    ) -> "Snapshots":
        environment = os.environ if environment is None else environment
        data = environment.get("TMT_PLAN_DATA") or environment.get("TMT_TEST_DATA")
        if not data:
            raise ValueError("TMT_PLAN_DATA or TMT_TEST_DATA must be set")
        return cls(Path(data) / "snapshots")

    def path(self, name: str) -> Path:
        if not name or name in {".", ".."} or Path(name).name != name:
            raise ValueError("snapshot name must be a single path component")
        return self.root / name

    def save(self, name: str, value: object) -> str:
        value = str(value)
        path = self.path(name)
        self.root.mkdir(parents=True, exist_ok=True)
        path.write_text(value, encoding="utf-8")
        return value

    def load(self, name: str) -> str:
        return self.path(name).read_text(encoding="utf-8")
