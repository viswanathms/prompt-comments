"""Comment-syntax definitions for the file formats and template engines
that AI prompts commonly live in.

A :class:`Dialect` is just a named bundle of line-comment markers and
block-comment delimiters. Dialects can be combined freely -- pass a list
of names to :func:`prompt_comments.strip_comments` to strip several
comment styles from the same text at once (handy for e.g. a Jinja
template that is also a Markdown document).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Tuple


@dataclass(frozen=True)
class LineComment:
    """A marker that comments out everything from itself to end of line."""

    marker: str


@dataclass(frozen=True)
class BlockComment:
    """A start/end delimiter pair that comments out everything between."""

    start: str
    end: str


@dataclass(frozen=True)
class Dialect:
    """A named collection of comment styles."""

    name: str
    line_comments: Tuple[LineComment, ...] = field(default_factory=tuple)
    block_comments: Tuple[BlockComment, ...] = field(default_factory=tuple)


# --- Reusable comment-style building blocks --------------------------------

_HASH_LINE = LineComment("#")
_SLASH_LINE = LineComment("//")
_DASH_LINE = LineComment("--")
_SEMI_LINE = LineComment(";")
_PERCENT_LINE = LineComment("%")

_JINJA_BLOCK = BlockComment("{#", "#}")
_HTML_BLOCK = BlockComment("<!--", "-->")
_C_BLOCK = BlockComment("/*", "*/")
_LIQUID_BLOCK = BlockComment("{% comment %}", "{% endcomment %}")
_MUSTACHE_LONG_BLOCK = BlockComment("{{!--", "--}}")
_MUSTACHE_SHORT_BLOCK = BlockComment("{{!", "}}")


def _dialect(name: str, *, line=(), block=()) -> Dialect:
    return Dialect(name=name, line_comments=tuple(line), block_comments=tuple(block))


# --- Named dialects ----------------------------------------------------------
#
# "default" is deliberately small: only comment styles that are very
# unlikely to collide with real prompt text. Format-specific dialects
# (yaml, python, sql, ...) add markers like `#`, `--`, `%` that *do*
# collide with plausible prompt content (Markdown headings, "item #3",
# LaTeX-ish text) -- opt into those explicitly via the `dialect` argument.

_BASE: Dict[str, Dialect] = {
    "default": _dialect("default", line=[_SLASH_LINE], block=[_JINJA_BLOCK, _HTML_BLOCK]),
    "jinja": _dialect("jinja", block=[_JINJA_BLOCK]),
    "django": _dialect("django", block=[_JINJA_BLOCK, _LIQUID_BLOCK]),
    "liquid": _dialect("liquid", block=[_LIQUID_BLOCK]),
    "handlebars": _dialect("handlebars", block=[_MUSTACHE_LONG_BLOCK, _MUSTACHE_SHORT_BLOCK]),
    "markdown": _dialect("markdown", block=[_HTML_BLOCK]),
    "html": _dialect("html", block=[_HTML_BLOCK]),
    "xml": _dialect("xml", block=[_HTML_BLOCK]),
    "yaml": _dialect("yaml", line=[_HASH_LINE]),
    "toml": _dialect("toml", line=[_HASH_LINE]),
    "ini": _dialect("ini", line=[_HASH_LINE, _SEMI_LINE]),
    "env": _dialect("env", line=[_HASH_LINE]),
    "json5": _dialect("json5", line=[_SLASH_LINE], block=[_C_BLOCK]),
    "python": _dialect("python", line=[_HASH_LINE]),
    "shell": _dialect("shell", line=[_HASH_LINE]),
    "sql": _dialect("sql", line=[_DASH_LINE], block=[_C_BLOCK]),
    "latex": _dialect("latex", line=[_PERCENT_LINE]),
    "c": _dialect("c", line=[_SLASH_LINE], block=[_C_BLOCK]),
}

# Aliases: alternate names that map to an existing dialect above.
_ALIASES: Dict[str, str] = {
    "jinja2": "jinja",
    "mustache": "handlebars",
    "jsonc": "json5",
    "bash": "shell",
    "sh": "shell",
    "zsh": "shell",
    "js": "c",
    "javascript": "c",
    "ts": "c",
    "typescript": "c",
    "go": "c",
    "golang": "c",
    "rust": "c",
    "java": "c",
    "csharp": "c",
    "cs": "c",
    "cpp": "c",
    "c++": "c",
}

DIALECTS: Dict[str, Dialect] = dict(_BASE)
for _alias, _target in _ALIASES.items():
    DIALECTS[_alias] = DIALECTS[_target]

# "all": every comment style from every named dialect, deduplicated. Handy
# as a maximal default, though it maximizes the odds of a false-positive
# match against literal prompt text -- prefer naming specific dialects.
_all_line = {lc for d in _BASE.values() for lc in d.line_comments}
_all_block = {bc for d in _BASE.values() for bc in d.block_comments}
DIALECTS["all"] = _dialect("all", line=sorted(_all_line, key=lambda l: l.marker), block=sorted(_all_block, key=lambda b: b.start))


def resolve_dialects(dialect):
    """Normalize a dialect argument into a list of :class:`Dialect` objects.

    `dialect` may be a dialect name, a :class:`Dialect` instance, or an
    iterable mixing either.
    """
    if isinstance(dialect, (str, Dialect)):
        items = [dialect]
    else:
        items = list(dialect)

    resolved = []
    for item in items:
        if isinstance(item, Dialect):
            resolved.append(item)
            continue
        name = str(item).lower()
        if name not in DIALECTS:
            raise ValueError(
                f"Unknown dialect {item!r}. Available dialects: {', '.join(sorted(DIALECTS))}"
            )
        resolved.append(DIALECTS[name])
    return resolved


def list_dialects():
    """Return the sorted list of known dialect names (including aliases)."""
    return sorted(DIALECTS)


# --- File-extension -> dialect mapping, used by prompt_comments.loader -----

EXTENSION_DIALECTS: Dict[str, str] = {
    ".md": "markdown",
    ".markdown": "markdown",
    ".j2": "jinja",
    ".jinja": "jinja",
    ".jinja2": "jinja",
    ".html": "html",
    ".htm": "html",
    ".xml": "xml",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".toml": "toml",
    ".ini": "ini",
    ".cfg": "ini",
    ".env": "env",
    ".json5": "json5",
    ".jsonc": "jsonc",
    ".py": "python",
    ".sh": "shell",
    ".bash": "shell",
    ".sql": "sql",
    ".tex": "latex",
    ".liquid": "liquid",
    ".hbs": "handlebars",
    ".handlebars": "handlebars",
    ".mustache": "mustache",
    ".js": "javascript",
    ".ts": "typescript",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".cs": "csharp",
    ".txt": "default",
}
