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
    blank_lines: Optional[str] = None,
    protect_code: bool = True,
) -> str:
    """Read a prompt file and return it with comments stripped.

    If ``dialect`` is omitted, it is inferred from the file extension
    (e.g. ``.j2`` -> ``jinja``, ``.md`` -> ``markdown``), falling back to
    ``"default"`` for unrecognized extensions. ``blank_lines`` and
    ``protect_code`` are passed through to :func:`~prompt_comments.core.strip_comments`.
    Line endings are preserved (CRLF stays CRLF).
    """
    path = Path(path)
    with open(path, "r", encoding=encoding, newline="") as f:
        text = f.read()
    if dialect is None:
        dialect = detect_dialect(path)
    return strip_comments(
        text,
        dialect=dialect,
        strip_blank_lines=strip_blank_lines,
        blank_lines=blank_lines,
        protect_code=protect_code,
    )
