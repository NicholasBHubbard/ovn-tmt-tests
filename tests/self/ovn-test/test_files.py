from pathlib import Path

import pytest
from ovn_test.files import find_text


def test_find_text_recurses_and_sorts_matching_files(tmp_path: Path) -> None:
    root = tmp_path / "root"
    nested = root / "nested"
    nested.mkdir(parents=True)
    match = nested / "match.fmf"
    match.write_text("OTT_EXAMPLE: value\n")
    first = root / "first.txt"
    first.write_text("OTT_EXAMPLE comes first\n")
    (root / "other.txt").write_text("nothing here\n")

    assert find_text(root, "OTT_EXAMPLE") == [first, match]


def test_find_text_accepts_a_direct_file(tmp_path: Path) -> None:
    match = tmp_path / "match.txt"
    match.write_text("needle\n")

    assert find_text(match, "needle") == [match]
    assert find_text(match, "missing") == []


def test_find_text_ignores_binary_files_and_symlinks(tmp_path: Path) -> None:
    root = tmp_path / "root"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (root / "invalid-utf8").write_bytes(b"\xffOTT_EXAMPLE")
    (root / "nul-byte").write_bytes(b"OTT_EXAMPLE\0")
    outside_match = outside / "match.txt"
    outside_match.write_text("OTT_EXAMPLE\n")
    file_link = root / "file-link"
    directory_link = root / "directory-link"
    file_link.symlink_to(outside_match)
    directory_link.symlink_to(outside, target_is_directory=True)

    assert find_text(root, "OTT_EXAMPLE") == []
    assert find_text(file_link, "OTT_EXAMPLE") == []


def test_find_text_handles_empty_and_missing_roots(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()

    assert find_text(empty, "anything") == []
    with pytest.raises(FileNotFoundError):
        find_text(tmp_path / "missing", "anything")
