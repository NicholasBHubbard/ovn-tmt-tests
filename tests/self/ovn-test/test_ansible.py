import subprocess
from pathlib import Path
from typing import Optional
from unittest.mock import Mock

import pytest
import yaml
from ovn_test.ansible import Ansible
from ovn_test.topology import Topology


def test_inventory_is_valid_and_preserves_connection_values(
    tmp_path: Path, topology: Topology
) -> None:
    ansible = Ansible(
        topology,
        tree=tmp_path,
        data=tmp_path / "data",
        key="/custom key",
        user="tester",
        environment={"OTT_DRIVER_CONNECT_TIMEOUT": "45"},
    )
    inventory_path = ansible.inventory(tmp_path / "nested/inventory.yml")

    subprocess.run(
        ["ansible-inventory", "-i", inventory_path, "--list"],
        check=True,
        capture_output=True,
        text=True,
    )
    inventory = yaml.safe_load(inventory_path.read_text())
    compute = inventory["all"]["hosts"]["compute-1"]
    assert compute["ansible_host"] == "192.0.2.2"
    assert compute["ansible_user"] == "tester"
    assert compute["ansible_ssh_private_key_file"] == "/custom key"
    assert "ConnectTimeout=45" in compute["ansible_ssh_common_args"]
    assert "IdentitiesOnly=yes" in compute["ansible_ssh_common_args"]
    assert set(inventory["all"]["children"]["compute"]["hosts"]) == {
        "compute-1",
        "compute-2",
    }


def test_from_environment_loads_topology_and_connection_defaults(
    tmp_path: Path, topology: Topology, monkeypatch: pytest.MonkeyPatch
) -> None:
    topology_path = tmp_path / "topology.yml"
    topology_path.write_text(yaml.safe_dump(topology.to_dict()))
    monkeypatch.setenv("TMT_TREE", str(tmp_path / "tree"))
    monkeypatch.setenv("TMT_TEST_DATA", str(tmp_path / "data"))
    monkeypatch.setenv("TMT_TOPOLOGY_YAML", str(topology_path))
    monkeypatch.setenv("OTT_DRIVER_RUNTIME_DIR", "/custom/driver")
    monkeypatch.setenv("OTT_DRIVER_USER", "tester")

    ansible = Ansible.from_environment()

    assert ansible.tree == tmp_path / "tree"
    assert ansible.data == tmp_path / "data"
    assert ansible.topology.guests() == ["compute-1", "central", "compute-2"]
    assert ansible.key == "/custom/driver/id_ed25519"
    assert ansible.user == "tester"


def test_from_environment_accepts_explicit_dependencies(
    tmp_path: Path, topology: Topology
) -> None:
    execute = Mock()
    ansible = Ansible.from_environment(
        topology=topology,
        environment={
            "TMT_TREE": str(tmp_path / "tree"),
            "TMT_TEST_DATA": str(tmp_path / "data"),
        },
        execute=execute,
        key="/explicit/key",
        user="operator",
    )

    assert ansible.topology is topology
    assert ansible.execute is execute
    assert ansible.key == "/explicit/key"
    assert ansible.user == "operator"


def test_run_executes_complete_topology_and_preserves_output(
    tmp_path: Path,
    topology: Topology,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("INHERITED_VARIABLE", "inherited")
    output = "TASK [setup]\nwarning between tasks\nTASK [verify]\n"
    completed = subprocess.CompletedProcess(["ansible-playbook"], 0, output)
    execute = Mock(return_value=completed)
    ansible = Ansible(
        topology,
        tree=tmp_path,
        data=tmp_path / "data",
        execute=execute,
        environment={"OTT_TEST_DEBUG": "true", "CUSTOM_VARIABLE": "preserved"},
    )

    result = ansible.run(
        "setup.yml",
        "-e",
        "example=true",
        log="logs/setup.log",
    )

    assert result is completed
    execute.assert_called_once()
    command = execute.call_args.args[0]
    options = execute.call_args.kwargs
    assert command == [
        "ansible-playbook",
        "-vvv",
        "-i",
        str(tmp_path / "data/ansible-inventory.yml"),
        "setup.yml",
        "-e",
        "example=true",
    ]
    assert "--limit" not in command
    assert options["cwd"] == tmp_path
    assert options["stdout"] is subprocess.PIPE
    assert options["stderr"] is subprocess.STDOUT
    assert options["env"]["CUSTOM_VARIABLE"] == "preserved"
    assert options["env"]["INHERITED_VARIABLE"] == "inherited"
    assert options["env"]["ANSIBLE_CONFIG"] == str(tmp_path / "ansible.cfg")
    assert options["env"]["ANSIBLE_HOST_KEY_CHECKING"] == "false"
    assert options["env"]["ANSIBLE_ROLES_PATH"] == str(tmp_path / "roles")
    assert (tmp_path / "data/logs/setup.log").read_text() == output
    assert capsys.readouterr().out == output


def test_run_honors_explicit_debug_and_absolute_log(
    tmp_path: Path, topology: Topology
) -> None:
    output = "successful output\n"
    execute = Mock(
        return_value=subprocess.CompletedProcess(["ansible-playbook"], 0, output)
    )
    ansible = Ansible(
        topology,
        tree=tmp_path,
        data=tmp_path / "data",
        execute=execute,
        environment={"OTT_TEST_DEBUG": "true"},
    )
    log = tmp_path / "absolute/setup.log"

    ansible.run("setup.yml", debug=False, log=log)

    assert "-vvv" not in execute.call_args.args[0]
    assert log.read_text() == output


@pytest.mark.parametrize(
    ("environment", "debug", "verbose"),
    (
        ({}, None, False),
        ({}, True, True),
    ),
)
def test_run_selects_verbosity(
    tmp_path: Path,
    topology: Topology,
    environment: dict[str, str],
    debug: Optional[bool],
    verbose: bool,
) -> None:
    execute = Mock(
        return_value=subprocess.CompletedProcess(["ansible-playbook"], 0, "")
    )
    ansible = Ansible(
        topology,
        tree=tmp_path,
        data=tmp_path / "data",
        execute=execute,
        environment=environment,
    )

    ansible.run("setup.yml", debug=debug)

    assert ("-vvv" in execute.call_args.args[0]) is verbose


def test_run_logs_output_before_raising_failure(
    tmp_path: Path,
    topology: Topology,
    capsys: pytest.CaptureFixture[str],
) -> None:
    output = "TASK [failed]\nfatal error\n"
    completed = subprocess.CompletedProcess(["ansible-playbook"], 7, output)
    ansible = Ansible(
        topology,
        tree=tmp_path,
        data=tmp_path / "data",
        execute=Mock(return_value=completed),
    )

    with pytest.raises(subprocess.CalledProcessError) as error:
        ansible.run("setup.yml")

    assert error.value.returncode == 7
    assert error.value.stdout == output
    assert error.value.stderr is None
    assert (tmp_path / "data/setup.log").read_text() == output
    assert capsys.readouterr().out == output


def test_run_rejects_invalid_debug_configuration(
    tmp_path: Path, topology: Topology
) -> None:
    execute = Mock()
    ansible = Ansible(
        topology,
        tree=tmp_path,
        data=tmp_path / "data",
        execute=execute,
        environment={"OTT_TEST_DEBUG": "sometimes"},
    )

    with pytest.raises(ValueError, match="OTT_TEST_DEBUG must be a boolean"):
        ansible.run("setup.yml")

    execute.assert_not_called()
    assert not (tmp_path / "data/setup.log").exists()
