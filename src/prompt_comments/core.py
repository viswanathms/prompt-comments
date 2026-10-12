"""Core comment-stripping logic."""

from __future__ import annotations

import re
from typing import Iterable, List, Optional, Tuple, Union

from .dialects import Dialect, resolve_dialects

DialectLike = Union[str, Dialect, Iterable[Union[str, Dialect]]]

BLANK_LINE_MODES = ("keep", "comment", "all")

_ESCAPE_PLACEHOLDER = "\0PROMPT_COMMENTS_ESCAPED\0"
_REMOVED_SENTINEL = "\0PROMPT_COMMENTS_REMOVED\0"
_CODE_PLACEHOLDER = "\0PROMPT_COMMENTS_CODE{}\0"
_CODE_PLACEHOLDER_RE = re.compile(r"\0PROMPT_COMMENTS_CODE(\d+)\0")

_FENCE_OPEN_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
_INLINE_CODE_RE = re.compile(r"`[^`\n]+`")


def strip_comments(
    text: str,
    dialect: DialectLike = "default",
    *,
    strip_blank_lines: bool = False,
    blank_lines: Optional[str] = None,
    protect_code: bool = True,
) -> str:
    """Remove comments from ``text``.

    Args:
        text: The prompt text to clean.
        dialect: A dialect name (e.g. ``"jinja"``), a :class:`~prompt_comments.dialects.Dialect`
            instance, or a list mixing either. Defaults to ``"default"``, a small
            set of comment styles ( ``{# #}``, ``<!-- -->``, ``//`` ) chosen to be
            unlikely to collide with real prompt text. See
            :func:`prompt_comments.dialects.list_dialects` for all available names.
        strip_blank_lines: Legacy flag, equivalent to ``blank_lines="all"``: every
            blank line is dropped.
        blank_lines: What to do with blank lines. ``"keep"`` (default) leaves them,
            ``"comment"`` drops only lines that became blank because a comment was
            removed (paragraph breaks you wrote are preserved), ``"all"`` drops every
            blank line. Overrides ``strip_blank_lines`` when given.
        protect_code: If ``True`` (default), fenced code blocks (```` ``` ```` /
            ``~~~``) and inline code spans (``\\`...\\```) are left untouched, so
            code samples inside a prompt keep their own comments.

    Returns:
        The text with all matching comments removed. When nothing matches, the
        very same ``str`` object is returned.

    A line-comment marker can be kept literally by escaping it with a
    backslash, e.g. ``\\# not a comment``.
    """
    mode = _resolve_blank_lines(strip_blank_lines, blank_lines)
    dialects = resolve_dialects(dialect)

    if not _may_contain_comment(text, dialects):
        return text

    spans: List[str] = []
    if protect_code:
        text, spans = _protect_code(text)

    text = _strip_block_comments(text, dialects)
    text = _strip_line_comments(text, dialects)
    text = _finalize(text, mode)

    if spans:
        text = _CODE_PLACEHOLDER_RE.sub(lambda m: spans[int(m.group(1))], text)
    if mode == "all":
        text = "\n".join(line for line in text.split("\n") if line.strip())
    return text


def _resolve_blank_lines(strip_blank_lines: bool, blank_lines: Optional[str]) -> str:
    if blank_lines is None:
        return "all" if strip_blank_lines else "keep"
    if blank_lines not in BLANK_LINE_MODES:
        raise ValueError(
            f"blank_lines must be one of {', '.join(BLANK_LINE_MODES)}; got {blank_lines!r}"
        )
    return blank_lines


def _may_contain_comment(text: str, dialects) -> bool:
    """Cheap pre-check so untouched text is returned as-is (same object)."""
    for d in dialects:
        for lc in d.line_comments:
            if lc.marker in text:
                return True
        for bc in d.block_comments:
            if bc.start in text:
                return True
    return False


def _protect_code(text: str) -> Tuple[str, List[str]]:
    """Swap fenced code blocks and inline code spans for placeholders."""
    spans: List[str] = []

    def stash(chunk: str) -> str:
        spans.append(chunk)
        return _CODE_PLACEHOLDER.format(len(spans) - 1)

    lines = text.split("\n")
    out: List[str] = []
    i, n = 0, len(lines)
    while i < n:
        m = _FENCE_OPEN_RE.match(lines[i])
        # A backtick fence's info string may not contain backticks (that's inline code).
        if m and not (m.group(1)[0] == "`" and "`" in lines[i][m.end():]):
            ch, size = m.group(1)[0], len(m.group(1))
            end = n - 1  # unterminated fence protects to the end of the text
            for j in range(i + 1, n):
                closing = lines[j].strip(" \t\r")
                indent = len(lines[j]) - len(lines[j].lstrip(" "))
                if indent <= 3 and len(closing) >= size and set(closing) == {ch}:
                    end = j
                    break
            out.append(stash("\n".join(lines[i : end + 1])))
            i = end + 1
        else:
            out.append(lines[i])
            i += 1

    text = "\n".join(out)
    text = _INLINE_CODE_RE.sub(lambda m: stash(m.group(0)), text)
    return text, spans


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
    return re.sub(pattern, lambda _m: _REMOVED_SENTINEL, text, flags=re.DOTALL)


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
    # `[^\r\n]*` (not `.*`) so CRLF line endings survive.
    comment_re = re.compile(r"(?:^|(?<=\s))(?:" + marker_pattern + r")[^\r\n]*", re.MULTILINE)
    text = comment_re.sub(lambda _m: _REMOVED_SENTINEL, text)

    return text.replace(_ESCAPE_PLACEHOLDER, "")


def _finalize(text: str, mode: str) -> str:
    """Drop the removal sentinels, per ``mode``, and trim trailing whitespace."""
    if mode == "comment":
        kept = []
        for line in text.split("\n"):
            if _REMOVED_SENTINEL in line:
                line = line.replace(_REMOVED_SENTINEL, "")
                if not line.strip():
                    continue
            kept.append(line)
        text = "\n".join(kept)
    else:
        text = text.replace(_REMOVED_SENTINEL, "")
    return re.sub(r"[ \t]+(?=\r?$)", "", text, flags=re.MULTILINE)
