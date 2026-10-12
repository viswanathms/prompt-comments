"""prompt_comments: write comments in your AI prompts, strip them before
they reach the model.

    >>> from prompt_comments import strip_comments
    >>> strip_comments("Summarize this. {# only for the 'concise' variant #}")
    'Summarize this.'

To strip comments from every LLM request automatically, see
:func:`prompt_comments.install` (in-process), ``prompt-comments proxy`` (local
HTTP proxy) and ``prompt-comments build`` (CLAUDE.md / AGENTS.md).
"""

from .core import strip_comments
from .dialects import Dialect, list_dialects
from .httpx_patch import install, uninstall, wrap_client, wrap_sdk_client
from .loader import detect_dialect, load_prompt
from .policy import Stats, StripPolicy

__all__ = [
    "strip_comments",
    "load_prompt",
    "detect_dialect",
    "list_dialects",
    "Dialect",
    "StripPolicy",
    "Stats",
    "install",
    "uninstall",
    "wrap_client",
    "wrap_sdk_client",
]

__version__ = "0.2.0"
