"""``import prompt_comments.auto`` -- strip comments from all httpx LLM calls in this process.

Set ``PROMPT_COMMENTS_DISABLED=1`` to turn it off without touching code.
"""

from .httpx_patch import install

stats = install()
