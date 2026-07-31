import os
import shutil

from ovn_test.command import Runner


class TestPreconditions:
    def test_kube_burner_is_absent(self) -> None:
        assert not shutil.which("kube-burner-ocp")


class TestResult:
    def test_requested_version_is_in_path(self) -> None:
        expected = os.environ["OTT_KUBE_BURNER_VERSION"]

        assert shutil.which("kube-burner-ocp")
        output = Runner().output("kube-burner-ocp", "version")
        versions = [
            line.removeprefix("Version: ")
            for line in output.splitlines()
            if line.startswith("Version: ")
        ]
        assert versions == [expected]
