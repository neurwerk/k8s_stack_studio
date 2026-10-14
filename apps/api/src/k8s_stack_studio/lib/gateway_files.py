"""Bounded reads from one projected-volume generation, without stale fallbacks."""

from __future__ import annotations

from pathlib import Path

MAX_DOCUMENT_BYTES = 1_048_576


class GatewayUnavailableError(Exception):
    """A missing, invalid or inconsistent public projection is unavailable."""


def projected_path(value: str, generations: dict[Path, Path]) -> Path:
    """Resolve ..data once per volume, including when reading sibling documents."""
    if not value:
        raise GatewayUnavailableError
    path = Path(value)
    if path.parent not in generations:
        data = path.parent / "..data"
        generations[path.parent] = data.resolve(strict=True) if data.is_symlink() else path.parent
    directory = generations[path.parent]
    return (directory / path.name).resolve(strict=True)


def read_document(path: Path) -> bytes:
    """Bound the actual read, not only a potentially outdated stat result."""
    with path.open("rb") as stream:
        data = stream.read(MAX_DOCUMENT_BYTES + 1)
    if len(data) > MAX_DOCUMENT_BYTES:
        raise GatewayUnavailableError
    return data
