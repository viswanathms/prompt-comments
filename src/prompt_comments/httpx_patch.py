"""Strip comments from every LLM request an httpx-based SDK sends.

The Anthropic and OpenAI SDKs (and litellm, langchain, ...) send requests through
``httpx`` -- or, in recent releases, ``httpx2``, an API-compatible fork. Wrapping
``send`` on whichever of the two is installed covers sync, async, streaming and
retried calls without any per-SDK code::

    import prompt_comments
    prompt_comments.install()          # every httpx/httpx2 client in this process

    prompt_comments.wrap_client(http_client)   # or just one client

Everything fails open: if cleaning raises, the original request is sent.
"""

from __future__ import annotations

import functools
import importlib
import os
import threading
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .payloads import clean_request_body
from .policy import Stats, StripPolicy, disabled_by_env

ENV_HOSTS = "PROMPT_COMMENTS_HOSTS"
HTTP_LIBRARIES = ("httpx", "httpx2")
_CLEANED_EXTENSION = "prompt_comments_cleaned"

_lock = threading.Lock()
_active: Optional["_Config"] = None
_originals: Dict[str, Tuple[Any, Any]] = {}  # library name -> (Client.send, AsyncClient.send)


class _Config:
    def __init__(self, policy: StripPolicy, hosts: Optional[Iterable[str]], stats: Stats) -> None:
        self.policy = policy
        self.hosts = frozenset(h.lower() for h in hosts) if hosts else None
        self.stats = stats


def _available_libraries() -> List[Any]:
    modules = []
    for name in HTTP_LIBRARIES:
        try:
            modules.append(importlib.import_module(name))
        except ImportError:
            continue
    if not modules:
        raise ImportError(
            "prompt_comments needs httpx (or httpx2) for in-process wrapping: "
            "pip install 'prompt-comments[httpx]'"
        )
    return modules


def _library_of(client: Any) -> Any:
    for cls in type(client).__mro__:
        name = str(getattr(cls, "__module__", "")).partition(".")[0]
        if name in HTTP_LIBRARIES:
            return importlib.import_module(name)
    raise TypeError(f"{type(client).__name__} is not an httpx / httpx2 client")


def _hosts_from_env() -> Optional[list]:
    raw = os.environ.get(ENV_HOSTS, "")
    names = [h.strip() for h in raw.split(",") if h.strip()]
    return names or None


def _rewrite(lib: Any, request: Any, cfg: _Config) -> Any:
    """Return ``request`` or, when comments were stripped, an equivalent new request."""
    try:
        if request.method != "POST" or request.extensions.get(_CLEANED_EXTENSION):
            return request
        if cfg.hosts is not None and request.url.host.lower() not in cfg.hosts:
            return request
        if "json" not in request.headers.get("content-type", "").lower():
            return request
        if request.headers.get("content-encoding"):
            return request
        try:
            raw = request.content
        except lib.RequestNotRead:  # streaming upload body
            return request
        new = clean_request_body(request.url.path, raw, cfg.policy, cfg.stats)
        if new is None:
            return request
        headers = [(k, v) for k, v in request.headers.multi_items() if k.lower() != "content-length"]
        extensions = {**request.extensions, _CLEANED_EXTENSION: True}
        return lib.Request(
            request.method, request.url, headers=headers, content=new, extensions=extensions
        )
    except Exception:  # fail open
        cfg.stats.add(errors=1)
        return request


def install(
    policy: Optional[StripPolicy] = None,
    *,
    hosts: Optional[Iterable[str]] = None,
    stats: Optional[Stats] = None,
) -> Stats:
    """Patch ``Client.send`` / ``AsyncClient.send`` of httpx and httpx2, process-wide.

    Args:
        policy: What to strip. Defaults to :meth:`StripPolicy.from_env`.
        hosts: Only touch requests to these hosts (default: any host whose URL path
            looks like an LLM endpoint; also settable via ``PROMPT_COMMENTS_HOSTS``).
        stats: Counters to update; a new :class:`Stats` is created if omitted.

    Calling it again just swaps the configuration. If the policy is disabled
    (``PROMPT_COMMENTS_DISABLED=1``) nothing is patched at all.
    Returns the :class:`Stats` object.
    """
    global _active
    policy = policy or StripPolicy.from_env()
    stats = stats or Stats()
    if not policy.enabled or disabled_by_env():
        return stats
    libraries = _available_libraries()
    cfg = _Config(policy, hosts if hosts is not None else _hosts_from_env(), stats)

    with _lock:
        _active = cfg
        for lib in libraries:
            if lib.__name__ not in _originals:
                _patch_library(lib)
    return stats


def _patch_library(lib: Any) -> None:
    sync_send, async_send = lib.Client.send, lib.AsyncClient.send

    @functools.wraps(sync_send)
    def patched_sync(self, request, *args, **kwargs):
        current = _active
        if current is not None:
            request = _rewrite(lib, request, current)
        return sync_send(self, request, *args, **kwargs)

    @functools.wraps(async_send)
    async def patched_async(self, request, *args, **kwargs):
        current = _active
        if current is not None:
            request = _rewrite(lib, request, current)
        return await async_send(self, request, *args, **kwargs)

    lib.Client.send = patched_sync
    lib.AsyncClient.send = patched_async
    _originals[lib.__name__] = (sync_send, async_send)


def uninstall() -> None:
    """Undo :func:`install`. Safe to call when not installed."""
    global _active
    with _lock:
        _active = None
        for name, (sync_send, async_send) in list(_originals.items()):
            lib = importlib.import_module(name)
            lib.Client.send, lib.AsyncClient.send = sync_send, async_send
            del _originals[name]


def is_installed() -> bool:
    return bool(_originals)


def wrap_client(
    client: Any,
    policy: Optional[StripPolicy] = None,
    *,
    hosts: Optional[Iterable[str]] = None,
    stats: Optional[Stats] = None,
) -> Any:
    """Strip comments for one ``httpx`` / ``httpx2`` client only.

    Returns ``client`` (modified in place), so it composes with SDK constructors::

        anthropic.Anthropic(http_client=wrap_client(httpx2.Client()))
    """
    policy = policy or StripPolicy.from_env()
    if not policy.enabled or disabled_by_env() or getattr(client, "_prompt_comments_wrapped", False):
        return client
    lib = _library_of(client)
    cfg = _Config(policy, hosts if hosts is not None else _hosts_from_env(), stats or Stats())
    original = client.send

    if isinstance(client, lib.AsyncClient):

        @functools.wraps(original)
        async def send(request, *args, **kwargs):
            return await original(_rewrite(lib, request, cfg), *args, **kwargs)

    else:

        @functools.wraps(original)
        def send(request, *args, **kwargs):
            return original(_rewrite(lib, request, cfg), *args, **kwargs)

    client.send = send
    client._prompt_comments_wrapped = True
    return client


def wrap_sdk_client(sdk_client: Any, policy: Optional[StripPolicy] = None, **kwargs: Any) -> Any:
    """Wrap an already-built ``anthropic`` / ``openai`` client (uses its ``_client`` http client)."""
    inner = getattr(sdk_client, "_client", None)
    if inner is None:
        raise TypeError("expected an SDK client exposing an httpx client as `_client`")
    wrap_client(inner, policy, **kwargs)
    return sdk_client
