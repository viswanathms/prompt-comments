"""Configuration shared by the in-process wrapper, the proxy and the CLI."""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from typing import Dict, FrozenSet, Optional

from .core import BLANK_LINE_MODES, DialectLike, strip_comments
from .dialects import resolve_dialects

DEFAULT_ROLES: FrozenSet[str] = frozenset({"system", "developer", "user"})
DEFAULT_MAX_BODY_BYTES = 32 * 1024 * 1024

ENV_DISABLED = "PROMPT_COMMENTS_DISABLED"
ENV_DIALECT = "PROMPT_COMMENTS_DIALECT"
ENV_ROLES = "PROMPT_COMMENTS_ROLES"
ENV_BLANK_LINES = "PROMPT_COMMENTS_BLANK_LINES"

_TRUE = {"1", "true", "yes", "on"}


def disabled_by_env(environ: Optional[Dict[str, str]] = None) -> bool:
    """True when ``PROMPT_COMMENTS_DISABLED`` is set: the kill switch beats any explicit policy."""
    env = os.environ if environ is None else environ
    return env.get(ENV_DISABLED, "").strip().lower() in _TRUE


@dataclass(frozen=True)
class StripPolicy:
    """What to strip from LLM request payloads, and how.

    ``roles`` limits stripping to messages of those roles; assistant turns, tool
    calls and tool results are never touched regardless of this setting.

    The default dialect is ``"blocks"`` (``<!-- -->`` and ``{# #}``): on the wire the
    text includes instructions you did not write, where a ``//`` in prose is not a
    comment. Opt into ``"default"`` (adds ``//`` line comments) when you control
    all of the text.
    """

    dialect: DialectLike = "blocks"
    roles: FrozenSet[str] = DEFAULT_ROLES
    blank_lines: str = "comment"
    protect_code: bool = True
    max_body_bytes: int = DEFAULT_MAX_BODY_BYTES
    enabled: bool = True

    def __post_init__(self) -> None:
        resolve_dialects(self.dialect)  # fail early on unknown dialect names
        if self.blank_lines not in BLANK_LINE_MODES:
            raise ValueError(f"blank_lines must be one of {', '.join(BLANK_LINE_MODES)}")
        object.__setattr__(self, "roles", frozenset(self.roles))

    @classmethod
    def from_env(cls, environ: Optional[Dict[str, str]] = None, **overrides) -> "StripPolicy":
        """Build a policy from ``PROMPT_COMMENTS_*`` environment variables."""
        env = os.environ if environ is None else environ
        kwargs: dict = {}
        if disabled_by_env(env):
            kwargs["enabled"] = False
        if env.get(ENV_DIALECT):
            names = [n.strip() for n in env[ENV_DIALECT].split(",") if n.strip()]
            kwargs["dialect"] = names[0] if len(names) == 1 else names
        if env.get(ENV_ROLES):
            kwargs["roles"] = frozenset(r.strip() for r in env[ENV_ROLES].split(",") if r.strip())
        if env.get(ENV_BLANK_LINES):
            kwargs["blank_lines"] = env[ENV_BLANK_LINES].strip()
        kwargs.update({k: v for k, v in overrides.items() if v is not None})
        return cls(**kwargs)

    def apply(self, text: str) -> str:
        return strip_comments(
            text,
            self.dialect,
            blank_lines=self.blank_lines,
            protect_code=self.protect_code,
        )


class Stats:
    """Thread-safe counters. Counts only; never stores prompt content."""

    _FIELDS = ("requests", "modified", "blocks_changed", "bytes_in", "bytes_out", "errors")

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counts = {name: 0 for name in self._FIELDS}

    def add(self, **deltas: int) -> None:
        with self._lock:
            for name, delta in deltas.items():
                self._counts[name] += delta

    def snapshot(self) -> Dict[str, int]:
        with self._lock:
            return dict(self._counts)
