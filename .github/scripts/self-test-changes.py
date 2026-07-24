#!/usr/bin/python3
import sys


IGNORED = {
    ".gitignore",
    "COPYING",
    "LICENSE",
    "README.md",
    "Unified-OVN-Test-System-Proposal.md",
}


def ignored(path):
    name = path.split("/", 1)[0]
    return (
        name in IGNORED
        or name.startswith(("COPYING.", "LICENSE."))
        or path.startswith("docs/")
    )


print(str(any(not ignored(path.rstrip()) for path in sys.stdin)).lower())
