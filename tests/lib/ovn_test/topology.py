import os
from pathlib import Path

import yaml


class Topology:
    def __init__(self, data):
        self.data = data
        self.current = data["guest"]["name"]

    @classmethod
    def from_file(cls, path):
        with Path(path).open() as source:
            return cls(yaml.safe_load(source))

    @classmethod
    def from_environment(cls):
        return cls.from_file(os.environ["TMT_TOPOLOGY_YAML"])

    def role(self, name):
        return list(self.data["roles"][name])

    def roles(self):
        return list(self.data["roles"])

    def guests(self):
        return list(self.data["guests"])

    def hostname(self, guest):
        return self.data["guests"][guest]["hostname"]

    def is_local(self, guest):
        return guest == self.current
