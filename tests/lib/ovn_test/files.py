import os
from pathlib import Path
from typing import Union


def find_text(root: Union[str, os.PathLike[str]], text: str) -> list[Path]:
    root = Path(root)
    if not root.exists():
        raise FileNotFoundError(root)
    if root.is_symlink():
        return []

    def contains(path: Path) -> bool:
        try:
            content = path.read_bytes()
            return b"\0" not in content and text in content.decode("utf-8")
        except UnicodeDecodeError:
            return False

    paths = [root] if root.is_file() else root.rglob("*")
    return sorted(
        path
        for path in paths
        if not path.is_symlink() and path.is_file() and contains(path)
    )
