"""File-aware convenience wrapper around :func:`prompt_comments.core.strip_comments`."""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Union

from .core import DialectLike, strip_comments
from .dialects import EXTENSION_DIALECTS


def detect_dialect(path: Union[str, Path]) -> str:
    """Guess a dialect name from a file's extension, defaulting to ``"default"``."""
    return EXTENSION_DIALECTS.get(Path(path).suffix.lower(), "default")


def load_prompt(
    path: Union[str, Path],
    dialect: Optional[DialectLike] = None,
    *,
    encoding: str = "utf-8",
    strip_blank_lines: bool = False,
) -> str:
    """Read a prompt file and return it with comments stripped.

    If ``dialect`` is omitted, it is inferred from the file extension
    (e.g. ``.j2`` -> ``jinja``, ``.md`` -> ``markdown``), falling back to
    ``"default"`` for unrecognized extensions.
    """
    path = Path(path)
    text = path.read_text(encoding=encoding)
    if dialect is None:
        dialect = detect_dialect(path)
    return strip_comments(text, dialect=dialect, strip_blank_lines=strip_blank_lines)
