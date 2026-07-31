from pathlib import Path

import pytest
from ovn_test.files import find_text


def test_find_text_recurses_and_reports_matching_files(tmp_path: Path) -> None:
    nested = tmp_path / "nested"
    nested.mkdir()
    match = nested / "match.fmf"
    match.write_text("OTT_EXAMPLE: value\n")
    (tmp_path / "other.txt").write_text("nothing here\n")
    (tmp_path / "binary").write_bytes(b"\xffOTT_EXAMPLE")

    assert find_text(tmp_path, "OTT_EXAMPLE") == [tmp_path / "binary", match]
    assert find_text(match, "missing") == []
    with pytest.raises(FileNotFoundError):
        find_text(tmp_path / "missing", "anything")
