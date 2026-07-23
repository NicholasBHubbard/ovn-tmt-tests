import shutil


class TestPreconditions:
    def test_brew_is_available(self):
        assert shutil.which("brew")


class TestResult:
    def test_build_tools_are_available(self):
        assert shutil.which("automake")
        assert shutil.which("libtool")
