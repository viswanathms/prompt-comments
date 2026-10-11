"""Strip comments out of LLM request payloads (Anthropic / OpenAI shapes).

The cleaners are pure and copy-on-write: they never mutate the body they are
given, they leave every key and block they do not understand untouched, and
they hand back the very same object when nothing changed.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, Iterable, Optional, Tuple

from .policy import Stats, StripPolicy, disabled_by_env

log = logging.getLogger("prompt_comments")

ANTHROPIC = "anthropic"
OPENAI_CHAT = "openai_chat"
OPENAI_RESPONSES = "openai_responses"

_ANTHROPIC_PATH = re.compile(r"/v1/messages(/count_tokens)?/?$")
_OPENAI_CHAT_PATH = re.compile(r"/chat/completions/?$")
_OPENAI_RESPONSES_PATH = re.compile(r"/responses/?$")


def detect_kind(path: str) -> Optional[str]:
    """Map a request URL path to a payload kind, or ``None`` if it isn't a known LLM call."""
    if _ANTHROPIC_PATH.search(path):
        return ANTHROPIC
    if _OPENAI_CHAT_PATH.search(path):
        return OPENAI_CHAT
    if _OPENAI_RESPONSES_PATH.search(path):
        return OPENAI_RESPONSES
    return None


def clean_payload(kind: str, body: Dict[str, Any], policy: StripPolicy) -> Tuple[Dict[str, Any], int]:
    """Return ``(new_body, blocks_changed)``; ``new_body is body`` when ``blocks_changed == 0``."""
    cleaner = _CLEANERS.get(kind)
    if cleaner is None or not isinstance(body, dict):
        return body, 0
    return cleaner(body, policy)


def clean_request_body(
    path: str,
    raw: bytes,
    policy: StripPolicy,
    stats: Optional[Stats] = None,
) -> Optional[bytes]:
    """Clean a raw JSON request body for ``path``.

    Returns the replacement bytes, or ``None`` when the request should be sent
    exactly as it is (not an LLM call, nothing to strip, too large, not JSON,
    disabled, or any error -- this function never raises).
    """
    if not policy.enabled or disabled_by_env():
        return None
    kind = detect_kind(path)
    if kind is None or not raw or len(raw) > policy.max_body_bytes:
        return None
    try:
        body = json.loads(raw)
        new_body, changed = clean_payload(kind, body, policy)
        if stats is not None:
            stats.add(requests=1)
        if not changed:
            return None
        new_raw = json.dumps(new_body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    except Exception as exc:  # fail open: a cleaning bug must never break an LLM call
        log.debug("prompt-comments: leaving request unchanged (%s: %s)", type(exc).__name__, exc)
        if stats is not None:
            stats.add(errors=1)
        return None
    if stats is not None:
        stats.add(modified=1, blocks_changed=changed, bytes_in=len(raw), bytes_out=len(new_raw))
    return new_raw


# --------------------------------------------------------------------------- helpers


def _clean_text(text: str, policy: StripPolicy) -> str:
    """Strip one text block. Never returns an empty string for a non-empty input."""
    cleaned = policy.apply(text)
    if cleaned is text or cleaned == text:
        return text
    if not cleaned.strip():
        return text  # providers reject empty text blocks; keep the original instead
    return cleaned


def _clean_content(content: Any, policy: StripPolicy, text_types: Iterable[str]) -> Tuple[Any, int]:
    """Clean a message ``content`` that is a string or a list of typed parts."""
    if isinstance(content, str):
        new = _clean_text(content, policy)
        return new, int(new != content)
    if not isinstance(content, list):
        return content, 0

    changed = 0
    parts = []
    for part in content:
        if isinstance(part, dict) and part.get("type") in text_types and isinstance(part.get("text"), str):
            new_text = _clean_text(part["text"], policy)
            if new_text != part["text"]:
                part = {**part, "text": new_text}
                changed += 1
        parts.append(part)
    return (parts, changed) if changed else (content, 0)


def _clean_messages(
    messages: Any, policy: StripPolicy, text_types: Iterable[str]
) -> Tuple[Any, int]:
    if not isinstance(messages, list):
        return messages, 0
    changed = 0
    out = []
    for msg in messages:
        if isinstance(msg, dict) and msg.get("role") in policy.roles:
            content, n = _clean_content(msg.get("content"), policy, text_types)
            if n:
                msg = {**msg, "content": content}
                changed += n
        out.append(msg)
    return (out, changed) if changed else (messages, 0)


# --------------------------------------------------------------------------- cleaners


def _clean_anthropic(body: Dict[str, Any], policy: StripPolicy) -> Tuple[Dict[str, Any], int]:
    new = dict(body)
    total = 0
    if "system" in policy.roles and "system" in body:
        new["system"], n = _clean_content(body["system"], policy, ("text",))
        total += n
    if "messages" in body:
        new["messages"], n = _clean_messages(body["messages"], policy, ("text",))
        total += n
    return (new, total) if total else (body, 0)


def _clean_openai_chat(body: Dict[str, Any], policy: StripPolicy) -> Tuple[Dict[str, Any], int]:
    if "messages" not in body:
        return body, 0
    messages, n = _clean_messages(body["messages"], policy, ("text",))
    return ({**body, "messages": messages}, n) if n else (body, 0)


def _clean_openai_responses(body: Dict[str, Any], policy: StripPolicy) -> Tuple[Dict[str, Any], int]:
    new = dict(body)
    total = 0
    if isinstance(body.get("instructions"), str) and policy.roles & {"system", "developer"}:
        new["instructions"] = _clean_text(body["instructions"], policy)
        total += int(new["instructions"] != body["instructions"])

    items = body.get("input")
    if isinstance(items, str):
        if "user" in policy.roles:
            new["input"] = _clean_text(items, policy)
            total += int(new["input"] != items)
    elif isinstance(items, list):
        new["input"], n = _clean_messages(items, policy, ("input_text",))
        total += n
    return (new, total) if total else (body, 0)


_CLEANERS = {
    ANTHROPIC: _clean_anthropic,
    OPENAI_CHAT: _clean_openai_chat,
    OPENAI_RESPONSES: _clean_openai_responses,
}
