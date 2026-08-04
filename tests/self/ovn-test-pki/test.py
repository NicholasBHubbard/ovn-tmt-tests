import grp
import json
from pathlib import Path

from ovn_test.command import Runner

ROOT = Path("/run/ovn-test-pki-self")
PRIVATE_KEY = ROOT / "identity/private.pem"
CERTIFICATE = ROOT / "identity/certificate.pem"
CA_CERT = ROOT / "trust/ca.pem"
STATE = Path("/tmp/ovn-test-pki-state.json")


def fingerprint(runner: Runner) -> str:
    return runner.output(
        "openssl",
        "x509",
        "-in",
        CERTIFICATE,
        "-noout",
        "-fingerprint",
        "-sha256",
    )


def credential_state(runner: Runner) -> dict[str, object]:
    return {
        "fingerprint": fingerprint(runner),
        "mtimes": {
            str(path): path.stat().st_mtime_ns
            for path in (PRIVATE_KEY, CERTIFICATE, CA_CERT)
        },
    }


def assert_valid_bundle(runner: Runner) -> None:
    runner.run("openssl", "verify", "-CAfile", CA_CERT, CERTIFICATE)
    for certificate in (CERTIFICATE, CA_CERT):
        runner.run("openssl", "x509", "-checkend", "60", "-noout", "-in", certificate)

    certificate_key = runner.output(
        "openssl", "x509", "-in", CERTIFICATE, "-pubkey", "-noout"
    )
    private_key = runner.output("openssl", "pkey", "-in", PRIVATE_KEY, "-pubout")
    assert certificate_key == private_key

    subject = runner.output(
        "openssl",
        "x509",
        "-in",
        CERTIFICATE,
        "-noout",
        "-subject",
        "-nameopt",
        "RFC2253",
    )
    assert subject == "subject=CN=OVN PKI self-test endpoint"

    details = runner.output("openssl", "x509", "-in", CERTIFICATE, "-text", "-noout")
    assert "TLS Web Server Authentication" in details
    assert "TLS Web Client Authentication" in details
    assert "CA:TRUE" in runner.output(
        "openssl", "x509", "-in", CA_CERT, "-text", "-noout"
    )

    service_gid = grp.getgrnam("openvswitch").gr_gid
    expected_modes = {
        PRIVATE_KEY: 0o640,
        CERTIFICATE: 0o644,
        CA_CERT: 0o644,
    }
    for path, mode in expected_modes.items():
        stat = path.stat()
        assert stat.st_mode & 0o777 == mode
        assert stat.st_gid == service_gid


class TestInitial:
    def test_valid_custom_path_bundle(self) -> None:
        runner = Runner()
        assert_valid_bundle(runner)
        STATE.write_text(json.dumps(credential_state(runner)))


class TestReapplied:
    def test_valid_bundle_was_unchanged(self) -> None:
        runner = Runner()
        assert_valid_bundle(runner)
        assert credential_state(runner) == json.loads(STATE.read_text())


class TestRegenerated:
    def test_corrupt_bundle_was_regenerated(self) -> None:
        runner = Runner()
        assert_valid_bundle(runner)
        assert fingerprint(runner) != json.loads(STATE.read_text())["fingerprint"]


class TestResult:
    def test_disabled_pki_was_removed(self) -> None:
        assert not ROOT.exists()
