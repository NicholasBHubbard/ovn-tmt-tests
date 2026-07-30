from pathlib import Path
from typing import Union


def find_text(root: Union[str, Path], text: str) -> list[Path]:
    root = Path(root)
    if not root.exists():
        raise FileNotFoundError(root)
    paths = [root] if root.is_file() else root.rglob("*")
    return sorted(
        path
        for path in paths
        if path.is_file() and text in path.read_text(errors="replace")
    )
