import hashlib
import json

import pytest

from ovn_test.command import Runner


REPOSITORY = "https://github.com/ovn-org/ovn.git"


@pytest.fixture
def artifact(tmp_path):
    path = tmp_path / "artifact.tar"
    path.write_bytes(b"")
    return path


@pytest.fixture
def manifest(tmp_path):
    return tmp_path / "manifest.json"


def identity(**changes):
    values = {
        "distribution": "test",
        "distribution_version": "2",
        "architecture": "test",
        "ovn_git_repo": REPOSITORY,
        "ovn_git_version": "main",
        "ovn_revision": "revision",
        "ovn_cc": "",
        "ovn_configure_flags": "",
        "ovn_make_flags": "",
        "ovn_werror": False,
        "ovn_dpdk": False,
        "ovn_dpdk_dir": "/usr/local/dpdk",
        "ovn_dpdk_version": "",
        "ovn_dpdk_checksum": "",
        "ovn_dpdk_drivers": "",
    }
    values.update(changes)
    return values


def write_manifest(path, values):
    path.write_text(json.dumps(values))


def playbook(runner, tree, path, variables):
    command = [
        "ansible-playbook",
        "-i",
        "localhost,",
        "-c",
        "local",
        path,
        "-e",
        "ansible_become=false",
    ]
    for name, value in variables.items():
        value = str(value).lower() if isinstance(value, bool) else value
        command.extend(("-e", f"{name}={value}"))
    return runner.run(*command, cwd=tree, check=False)


def install(runner, tree, artifact, manifest, **variables):
    return playbook(
        runner,
        tree,
        "playbooks/ovn-install.yml",
        {
            "ansible_distribution": "test",
            "ansible_distribution_version": 2,
            "ansible_architecture": "test",
            "ovn_install_method": "artifact",
            "ovn_artifact_manifest_local_path": manifest,
            "ovn_artifact_local_path": artifact,
            **variables,
        },
    )


def validate(runner, tree, artifact, manifest, **variables):
    return playbook(
        runner,
        tree,
        "tests/self/contracts/validate-artifact.yml",
        {
            "ovn_artifact_expected_distribution": "test",
            "ovn_artifact_expected_distribution_version": 2,
            "ovn_artifact_expected_architecture": "test",
            "ovn_artifact_manifest_local_path": manifest,
            "ovn_artifact_local_path": artifact,
            **variables,
        },
    )


def assert_rejected(result, message):
    assert result.returncode
    assert message in result.stdout + result.stderr


@pytest.mark.parametrize(
    ("distribution", "version", "architecture"),
    [
        ("wrong", "2", "test"),
        ("test", "1", "test"),
        ("test", "2", "wrong"),
    ],
)
def test_incompatible_host_is_rejected(
    tree,
    artifact,
    manifest,
    distribution,
    version,
    architecture,
):
    write_manifest(
        manifest,
        {
            "distribution": distribution,
            "distribution_version": version,
            "architecture": architecture,
        },
    )
    result = install(Runner(), tree, artifact, manifest)
    assert_rejected(result, "OVN artifact is incompatible with this host.")


def test_build_configuration_mismatch_is_rejected(tree, artifact, manifest):
    write_manifest(manifest, identity(ovn_git_repo="wrong"))
    result = install(Runner(), tree, artifact, manifest)
    assert_rejected(
        result,
        "OVN artifact build configuration does not match the request.",
    )


def test_reuse_requires_revision(tree, artifact, manifest):
    write_manifest(manifest, identity(ovn_revision="old", sha256="wrong"))
    result = install(
        Runner(),
        tree,
        artifact,
        manifest,
        ovn_artifact_build=False,
    )
    assert_rejected(
        result,
        "Set ovn_artifact_expected_revision when reusing an OVN artifact.",
    )


def test_revision_mismatch_is_rejected(tree, artifact, manifest):
    write_manifest(manifest, identity(ovn_revision="old", sha256="wrong"))
    result = install(
        Runner(),
        tree,
        artifact,
        manifest,
        ovn_artifact_expected_revision="new",
    )
    assert_rejected(
        result,
        "OVN artifact source revision does not match the request.",
    )


def test_dpdk_identity_mismatch_is_rejected(tree, artifact, manifest):
    write_manifest(
        manifest,
        identity(
            ovn_dpdk=True,
            ovn_dpdk_version="wrong",
            ovn_dpdk_checksum="wrong",
            ovn_dpdk_drivers="wrong",
            sha256="wrong",
        ),
    )
    result = install(
        Runner(),
        tree,
        artifact,
        manifest,
        ovn_install_dpdk_enabled=True,
        ovn_install_dpdk_version="24.11.1",
        ovn_install_dpdk_checksum="checksum",
        ovn_install_dpdk_drivers="drivers",
    )
    assert_rejected(
        result,
        "OVN artifact build configuration does not match the request.",
    )


def test_bad_checksum_is_rejected(tree, artifact, manifest):
    write_manifest(manifest, identity(sha256="wrong"))
    result = install(Runner(), tree, artifact, manifest)
    assert_rejected(
        result,
        "OVN artifact is missing or its checksum does not match.",
    )


def test_non_installing_consumer_can_validate(tree, artifact, manifest):
    checksum = hashlib.sha256(artifact.read_bytes()).hexdigest()
    write_manifest(manifest, identity(sha256=checksum))
    assert validate(Runner(), tree, artifact, manifest).returncode == 0


def test_invalid_artifact_action_is_rejected(tree, artifact, manifest):
    checksum = hashlib.sha256(artifact.read_bytes()).hexdigest()
    write_manifest(manifest, identity(sha256=checksum))
    result = validate(
        Runner(),
        tree,
        artifact,
        manifest,
        ovn_artifact_action="invalid",
    )
    assert_rejected(result, "ovn_artifact_action must be build or validate.")


def test_missing_reusable_artifact_is_rejected(tree, tmp_path, manifest):
    result = playbook(
        Runner(),
        tree,
        "playbooks/ovn-build-artifact.yml",
        {
            "ovn_artifact_builder_hosts": "all",
            "ovn_artifact_build": False,
            "ovn_artifact_expected_revision": "revision",
            "ovn_artifact_local_path": tmp_path / "missing.tar",
            "ovn_artifact_manifest_local_path": tmp_path / "missing.json",
        },
    )
    assert_rejected(result, "The requested reusable OVN artifact is missing.")
