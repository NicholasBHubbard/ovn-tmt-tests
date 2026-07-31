import subprocess
from pathlib import Path
from typing import Any

import pytest
from ovn_test.ansible import Ansible
from ovn_test.topology import Topology

from ._support import topology_data


def test_ansible_writes_inventory_and_keeps_per_guest_logs(tmp_path: Path) -> None:
    calls = []

    def execute(command: Any, **kwargs: Any) -> Any:
        calls.append((command, kwargs))
        guest = command[command.index("--limit") + 1]
        status = 7 if guest == "compute-1" else 0
        return subprocess.CompletedProcess(
            command,
            status,
            f"TASK [{guest}]\n",
            f"stderr-{guest}\n",
        )

    data = tmp_path / "data"
    ansible = Ansible(
        Topology(topology_data()),
        tree=tmp_path,
        data=data,
        execute=execute,
        environment={
            "OTT_DRIVER_KEY_PATH": "/custom/key",
            "OTT_DRIVER_RUNTIME_DIR": "/custom/driver",
            "OTT_DRIVER_USER": "tester",
            "OTT_TEST_DEBUG": "true",
        },
    )

    with pytest.raises(subprocess.CalledProcessError) as error:
        ansible.run("setup.yml", "-e", "example=true")

    assert error.value.returncode == 7
    inventory = (data / "ansible-inventory.ini").read_text()
    assert "[all]" in inventory
    assert "compute-1 ansible_host=192.0.2.2 ansible_user=tester" in inventory
    assert "ansible_ssh_private_key_file=/custom/key" in inventory
    assert "[compute]\ncompute-1\ncompute-2\n" in inventory
    assert len(calls) == 3
    assert all("-vvv" in command for command, kwargs in calls)
    assert all(kwargs["cwd"] == tmp_path for command, kwargs in calls)
    assert all(
        kwargs["env"]["ANSIBLE_ROLES_PATH"] == str(tmp_path / "roles")
        for command, kwargs in calls
    )
    assert "TASK [compute-1]" in (data / "setup-compute-1.log").read_text()
    combined = (data / "setup.log").read_text()
    assert "===== central =====" in combined
    assert "===== compute-1 =====" in combined


def test_ansible_uses_tmt_environment_paths(tmp_path: Path) -> None:
    environment = {
        "TMT_TREE": str(tmp_path / "tree"),
        "TMT_TEST_DATA": str(tmp_path / "data"),
    }

    ansible = Ansible.from_environment(
        topology=Topology(topology_data()),
        execute=lambda command, **kwargs: subprocess.CompletedProcess(
            command, 0, "", ""
        ),
        environment=environment,
    )

    assert ansible.tree == tmp_path / "tree"
    assert ansible.data == tmp_path / "data"
