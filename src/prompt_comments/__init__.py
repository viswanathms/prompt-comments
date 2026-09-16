"""prompt_comments: write comments in your AI prompts, strip them before
they reach the model.

    >>> from prompt_comments import strip_comments
    >>> strip_comments("Summarize this. {# only for the 'concise' variant #}")
    'Summarize this.'
"""

from .core import strip_comments
from .dialects import Dialect, list_dialects
from .loader import detect_dialect, load_prompt

__all__ = [
    "strip_comments",
    "load_prompt",
    "detect_dialect",
    "list_dialects",
    "Dialect",
]

__version__ = "0.1.0"
