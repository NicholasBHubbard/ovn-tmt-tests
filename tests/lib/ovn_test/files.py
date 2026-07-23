from pathlib import Path


def find_text(root, text):
    root = Path(root)
    if not root.exists():
        raise FileNotFoundError(root)
    paths = [root] if root.is_file() else root.rglob("*")
    return sorted(
        path
        for path in paths
        if path.is_file() and text in path.read_text(errors="replace")
    )
