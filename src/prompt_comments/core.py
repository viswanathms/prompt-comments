"""Core comment-stripping logic."""

from __future__ import annotations

import re
from typing import Iterable, Union

from .dialects import Dialect, resolve_dialects

DialectLike = Union[str, Dialect, Iterable[Union[str, Dialect]]]

_ESCAPE_PLACEHOLDER = "\0PROMPT_COMMENTS_ESCAPED\0"


def strip_comments(text: str, dialect: DialectLike = "default", *, strip_blank_lines: bool = False) -> str:
    """Remove comments from ``text``.

    Args:
        text: The prompt text to clean.
        dialect: A dialect name (e.g. ``"jinja"``), a :class:`~prompt_comments.dialects.Dialect`
            instance, or a list mixing either. Defaults to ``"default"``, a small
            set of comment styles ( ``{# #}``, ``<!-- -->``, ``//`` ) chosen to be
            unlikely to collide with real prompt text. See
            :func:`prompt_comments.dialects.list_dialects` for all available names.
        strip_blank_lines: If ``True``, lines that become empty after a comment
            is removed are dropped entirely instead of left as blank lines.

    Returns:
        The text with all matching comments removed.

    A line-comment marker can be kept literally by escaping it with a
    backslash, e.g. ``\\# not a comment``.
    """
    dialects = resolve_dialects(dialect)
    text = _strip_block_comments(text, dialects)
    text = _strip_line_comments(text, dialects)
    if strip_blank_lines:
        text = "\n".join(line for line in text.split("\n") if line.strip())
    return text


def _strip_block_comments(text: str, dialects) -> str:
    blocks = []
    seen = set()
    for d in dialects:
        for block in d.block_comments:
            key = (block.start, block.end)
            if key not in seen:
                seen.add(key)
                blocks.append(block)
    if not blocks:
        return text

    # Longer start delimiters first, so e.g. `{{!--` is tried before `{{!`.
    blocks.sort(key=lambda b: len(b.start), reverse=True)
    pattern = "|".join(re.escape(b.start) + r".*?" + re.escape(b.end) for b in blocks)
    return re.sub(pattern, "", text, flags=re.DOTALL)


def _strip_line_comments(text: str, dialects) -> str:
    markers = set()
    for d in dialects:
        for lc in d.line_comments:
            markers.add(lc.marker)
    if not markers:
        return text

    # Longest markers first so e.g. `--` isn't a partial match ahead of a
    # hypothetical `---` marker.
    ordered = sorted(markers, key=len, reverse=True)
    marker_pattern = "|".join(re.escape(m) for m in ordered)

    escaped_re = re.compile(r"\\(" + marker_pattern + r")")
    text = escaped_re.sub(lambda m: _ESCAPE_PLACEHOLDER + m.group(1), text)

    # A marker only starts a comment at the beginning of a line or after
    # whitespace -- this keeps things like `https://example.com` and
    # `color: #fff` mid-token intact in common cases (URLs specifically:
    # the char before `//` there is `:`, not whitespace, so it's skipped).
    comment_re = re.compile(r"(?:^|(?<=\s))(?:" + marker_pattern + r").*$", re.MULTILINE)
    text = comment_re.sub("", text)

    text = text.replace(_ESCAPE_PLACEHOLDER, "")
    text = re.sub(r"[ \t]+$", "", text, flags=re.MULTILINE)
    return text
