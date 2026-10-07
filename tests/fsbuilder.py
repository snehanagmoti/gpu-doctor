"""Build a fake filesystem tree on disk from a ``{path: content}`` dict.

Scenarios are written as Python dicts (see ``scenarios.py``) instead of
checked-in directory trees, so each broken scenario can be expressed as a
small, reviewable *diff* against the healthy one ("same machine, but the
kernel was upgraded and DKMS did not rebuild").
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Symlink:
    target: str  # absolute targets are resolved inside the fake root by the probe


@dataclass(frozen=True)
class Dir:
    """An empty directory."""


Content = str | bytes | Symlink | Dir | None  # None deletes a path from a scenario


def materialise(
    root: Path, files: dict[str, Content], where: Callable[[str], Path] | None = None
) -> None:
    """Write ``files`` under ``root``; ``where`` can remap system paths (snap hostfs)."""
    for path, content in files.items():
        if content is None:
            continue
        dest = where(path) if where else root / path.lstrip("/")
        if isinstance(content, Dir):
            dest.mkdir(parents=True, exist_ok=True)
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, Symlink):
            os.symlink(content.target, dest)
        elif isinstance(content, bytes):
            dest.write_bytes(content)
        else:
            dest.write_text(content)
