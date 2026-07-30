import os
from pathlib import Path
from typing import Any, Union

import yaml


class Topology:
    def __init__(self, data: dict[str, Any]) -> None:
        self.data = data
        self.current = data["guest"]["name"]

    @classmethod
    def from_file(cls, path: Union[str, os.PathLike[str]]) -> "Topology":
        with Path(path).open() as source:
            return cls(yaml.safe_load(source))

    @classmethod
    def from_environment(cls) -> "Topology":
        return cls.from_file(os.environ["TMT_TOPOLOGY_YAML"])

    def role(self, name: str) -> list[str]:
        return list(self.data["roles"][name])

    def roles(self) -> list[str]:
        return list(self.data["roles"])

    def guests(self) -> list[str]:
        return list(self.data["guests"])

    def hostname(self, guest: str) -> str:
        return self.data["guests"][guest]["hostname"]

    def is_local(self, guest: str) -> bool:
        return guest == self.current
