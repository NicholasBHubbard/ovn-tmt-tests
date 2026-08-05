from typing import Any

import pytest
from ovn_test.topology import Topology


@pytest.fixture
def topology() -> Topology:
    data: dict[str, Any] = {
        "guest": {"name": "central", "hostname": "192.0.2.1", "role": "central"},
        "guests": {
            "central": {
                "name": "central",
                "hostname": "192.0.2.1",
                "role": "central",
            },
            "compute-1": {
                "name": "compute-1",
                "hostname": "192.0.2.2",
                "role": "compute",
            },
            "compute-2": {
                "name": "compute-2",
                "hostname": "192.0.2.3",
                "role": "compute",
            },
        },
        "roles": {"central": ["central"], "compute": ["compute-1", "compute-2"]},
    }
    return Topology(data)
