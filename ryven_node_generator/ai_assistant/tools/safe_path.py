"""Resolve user-supplied relative paths inside a trusted root (no traversal)."""

from __future__ import annotations

from pathlib import Path


def resolve_under_root(root: Path, relative: str) -> Path:
    """Return absolute path if it stays under ``root.resolve()``."""
    raw = (relative or "").strip().replace("\\", "/")
    raw = raw.lstrip("/")
    if not raw or raw.startswith("..") or "/../" in raw or raw.endswith("/.."):
        raise ValueError("invalid path")
    parts = Path(raw).parts
    if ".." in parts:
        raise ValueError("path must not contain ..")
    root_r = root.expanduser().resolve()
    full = (root_r / raw).resolve()
    try:
        full.relative_to(root_r)
    except ValueError as exc:
        raise ValueError("path escapes project root") from exc
    return full
