"""A local HTTP proxy that strips comments from LLM requests on the wire.

Point a tool at it instead of the provider and everything it sends -- including
the CLAUDE.md / AGENTS.md text Claude Code and Codex put into their requests --
is cleaned before it leaves your machine::

    prompt-comments proxy                      # listens on 127.0.0.1:8787
    export ANTHROPIC_BASE_URL=http://127.0.0.1:8787
    export OPENAI_BASE_URL=http://127.0.0.1:8787/v1

Design notes:

* Stdlib only. Request bodies are rewritten with the same code as the
  in-process wrapper (:func:`prompt_comments.payloads.clean_request_body`).
* Responses are streamed back untouched and undecoded.
* Fail open: any problem while cleaning forwards the original bytes.
* Prompt text, headers and API keys are never logged.
* Binds to loopback and rejects foreign ``Host`` headers (DNS-rebinding guard).
"""

from __future__ import annotations

import argparse
import http.client
import json
import logging
import ssl
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, List, Optional, Sequence, Tuple
from urllib.parse import urlsplit

from .payloads import clean_request_body
from .policy import DEFAULT_ROLES, Stats, StripPolicy

log = logging.getLogger("prompt_comments.proxy")

DEFAULT_PORT = 8787
DEFAULT_ANTHROPIC_UPSTREAM = "https://api.anthropic.com"
DEFAULT_OPENAI_UPSTREAM = "https://api.openai.com"

CONNECT_TIMEOUT = 15
IDLE_READ_TIMEOUT = 300  # idle, not total: long SSE streams are fine

_LOOPBACK = {"localhost", "127.0.0.1", "::1"}
_HOP_BY_HOP = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "proxy-connection", "te", "trailer", "transfer-encoding", "upgrade",
}
_DROP_REQUEST = _HOP_BY_HOP | {"host", "content-length"}
_DROP_RESPONSE = _HOP_BY_HOP | {"date", "server"}
_ANTHROPIC_PATHS = ("/v1/messages", "/v1/complete")


class ProxyConfig:
    def __init__(
        self,
        *,
        host: str = "127.0.0.1",
        port: int = DEFAULT_PORT,
        anthropic_upstream: str = DEFAULT_ANTHROPIC_UPSTREAM,
        openai_upstream: str = DEFAULT_OPENAI_UPSTREAM,
        policy: Optional[StripPolicy] = None,
        dry_run: bool = False,
        debug_diff: bool = False,
        allowed_hosts: Sequence[str] = (),
    ) -> None:
        self.host = host
        self.port = port
        self.upstreams = {
            "anthropic": _parse_upstream(anthropic_upstream),
            "openai": _parse_upstream(openai_upstream),
        }
        self.policy = policy or StripPolicy.from_env()
        self.dry_run = dry_run
        self.debug_diff = debug_diff
        self.allowed_hosts = {h.lower() for h in allowed_hosts}
        if host.lower() in _LOOPBACK:
            self.allowed_hosts |= _LOOPBACK
        else:
            self.allowed_hosts.add(host.lower())
        self.stats = Stats()


class _Upstream:
    def __init__(self, scheme: str, host: str, port: Optional[int], prefix: str) -> None:
        self.scheme, self.host, self.port, self.prefix = scheme, host, port, prefix

    def connect(self) -> http.client.HTTPConnection:
        if self.scheme == "https":
            conn: http.client.HTTPConnection = http.client.HTTPSConnection(
                self.host, self.port, timeout=CONNECT_TIMEOUT, context=_ssl_context()
            )
        else:
            conn = http.client.HTTPConnection(self.host, self.port, timeout=CONNECT_TIMEOUT)
        conn.connect()
        conn.sock.settimeout(IDLE_READ_TIMEOUT)
        return conn


_SSL_HINT = (
    "TLS certificate verification failed. On macOS with a python.org Python, run "
    "'/Applications/Python 3.x/Install Certificates.command' (or: pip install certifi). "
    "Behind a TLS-inspecting corporate proxy, set SSL_CERT_FILE to your CA bundle."
)
_ssl_ctx: Optional[ssl.SSLContext] = None


def _ssl_context() -> ssl.SSLContext:
    """Default verifying context; falls back to ``certifi`` when Python has no root certs.

    python.org builds on macOS ship without a CA bundle until their
    ``Install Certificates.command`` is run. ``SSL_CERT_FILE`` is honoured by OpenSSL.
    """
    global _ssl_ctx
    if _ssl_ctx is None:
        ctx = ssl.create_default_context()
        if not ctx.cert_store_stats().get("x509_ca"):
            try:
                import certifi

                ctx.load_verify_locations(certifi.where())
            except ImportError:
                pass
        _ssl_ctx = ctx
    return _ssl_ctx


def _parse_upstream(url: str) -> _Upstream:
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ValueError(f"invalid upstream URL: {url!r}")
    if parts.scheme == "http" and parts.hostname.lower() not in _LOOPBACK:
        raise ValueError(f"refusing plain-http upstream {url!r}: only https:// (or loopback http://) is allowed")
    return _Upstream(parts.scheme, parts.hostname, parts.port, parts.path.rstrip("/"))


def _is_loopback(host: str) -> bool:
    return host.lower() in _LOOPBACK


def _error_body(kind: str, message: str, code: str) -> bytes:
    if kind == "anthropic":
        payload: Dict[str, Any] = {"type": "error", "error": {"type": "api_error", "message": message}}
    else:
        payload = {"error": {"message": message, "type": "proxy_error", "code": code}}
    return json.dumps(payload).encode()


def _changed_strings(old: Any, new: Any, limit: int = 160) -> List[Tuple[str, str]]:
    """Walk two JSON trees and list the strings that differ (for --debug-diff)."""
    found: List[Tuple[str, str]] = []
    if isinstance(old, str) and isinstance(new, str):
        if old != new:
            found.append((old[:limit], new[:limit]))
    elif isinstance(old, dict) and isinstance(new, dict):
        for key in old.keys() & new.keys():
            found.extend(_changed_strings(old[key], new[key], limit))
    elif isinstance(old, list) and isinstance(new, list) and len(old) == len(new):
        for a, b in zip(old, new):
            found.extend(_changed_strings(a, b, limit))
    return found


class ProxyHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "prompt-comments-proxy"
    config: ProxyConfig  # set on the subclass built by make_server()

    # -- plumbing ---------------------------------------------------------------

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - stdlib signature
        log.debug("%s %s", self.address_string(), format % args)

    def _send_json(self, status: int, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _read_body(self) -> Optional[bytes]:
        if "chunked" in self.headers.get("Transfer-Encoding", "").lower():
            chunks = []
            while True:
                size = int(self.rfile.readline().split(b";")[0].strip() or b"0", 16)
                if size == 0:
                    while self.rfile.readline() not in (b"\r\n", b"\n", b""):
                        pass  # trailers
                    break
                chunks.append(self.rfile.read(size))
                self.rfile.read(2)
            return b"".join(chunks)
        length = int(self.headers.get("Content-Length") or 0)
        if length:
            return self.rfile.read(length)
        return b"" if self.command in ("POST", "PUT", "PATCH") else None

    def _route(self, path: str) -> str:
        if path.startswith(_ANTHROPIC_PATHS) or "anthropic-version" in self.headers:
            return "anthropic"
        return "openai"

    # -- request handling ----------------------------------------------------------

    def _handle(self) -> None:
        cfg = self.config
        host_header = self.headers.get("Host", "")
        hostname = (urlsplit("//" + host_header).hostname or "").lower()
        if hostname not in cfg.allowed_hosts:
            self._send_json(421, b'{"error":"misdirected request: unexpected Host header"}')
            self.close_connection = True
            return

        path = urlsplit(self.path).path
        if self.command == "GET" and path == "/health":
            return self._send_json(200, b'{"status":"ok"}')
        if self.command == "GET" and path == "/stats":
            payload = {"dry_run": cfg.dry_run, **cfg.stats.snapshot()}
            return self._send_json(200, json.dumps(payload).encode())

        try:
            body = self._read_body()
        except (ValueError, OSError):
            self._send_json(400, b'{"error":"malformed request body"}')
            self.close_connection = True
            return

        kind = self._route(path)
        body = self._maybe_clean(path, body)

        headers = [(k, v) for k, v in self.headers.items() if k.lower() not in _DROP_REQUEST]
        conn = None
        try:
            upstream = cfg.upstreams[kind]
            conn = upstream.connect()
            conn.putrequest(self.command, upstream.prefix + self.path, skip_host=False, skip_accept_encoding=True)
            for key, value in headers:
                conn.putheader(key, value)
            if body is not None:
                conn.putheader("Content-Length", str(len(body)))
            conn.endheaders(body)
            self._relay_response(conn.getresponse())
        except (OSError, http.client.HTTPException) as exc:
            reason = type(exc).__name__
            if isinstance(exc, ssl.SSLCertVerificationError):
                reason += f": {_SSL_HINT}"
            log.warning("upstream %s error: %s", kind, reason)
            self._send_json(502, _error_body(kind, f"prompt-comments proxy: upstream unreachable ({reason})", "upstream_unreachable"))
            self.close_connection = True
        finally:
            if conn is not None:
                conn.close()

    def _maybe_clean(self, path: str, body: Optional[bytes]) -> Optional[bytes]:
        cfg = self.config
        if not body or self.headers.get("Content-Encoding"):
            return body
        new = clean_request_body(path, body, cfg.policy, cfg.stats)
        if new is None:
            return body
        if cfg.dry_run or cfg.debug_diff:
            log.info("%s: %d bytes -> %d bytes (%s)", "dry-run" if cfg.dry_run else "cleaned",
                     len(body), len(new), path)
        if cfg.debug_diff:
            try:
                for before, after in _changed_strings(json.loads(body), json.loads(new)):
                    log.info("  - %r\n  + %r", before, after)
            except ValueError:
                pass
        return body if cfg.dry_run else new

    def _relay_response(self, resp: http.client.HTTPResponse) -> None:
        self.send_response(resp.status, resp.reason)
        has_length = False
        for key, value in resp.getheaders():
            lower = key.lower()
            if lower in _DROP_RESPONSE:
                continue
            has_length = has_length or lower == "content-length"
            self.send_header(key, value)
        body_expected = self.command != "HEAD" and resp.status not in (204, 304) and resp.status >= 200
        if not has_length and body_expected:
            self.send_header("Connection", "close")  # body is delimited by closing, as with SSE
            self.close_connection = True
        self.end_headers()
        if not body_expected:
            return
        try:
            while True:
                chunk = resp.read1(8192)
                if not chunk:
                    break
                self.wfile.write(chunk)
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            self.close_connection = True  # client went away mid-stream

    do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = do_OPTIONS = do_HEAD = _handle


class ProxyServer(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request: Any, client_address: Any) -> None:
        # Clients routinely drop idle keep-alive connections; that is not an error.
        if isinstance(sys.exc_info()[1], (ConnectionError, TimeoutError)):
            log.debug("connection from %s closed: %s", client_address, sys.exc_info()[1])
            return
        super().handle_error(request, client_address)


def make_server(config: ProxyConfig) -> ProxyServer:
    handler = type("BoundProxyHandler", (ProxyHandler,), {"config": config})
    return ProxyServer((config.host, config.port), handler)


def env_exports(host: str, port: int) -> str:
    base = f"http://{host}:{port}"
    return f"export ANTHROPIC_BASE_URL={base}\nexport OPENAI_BASE_URL={base}/v1"


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("action", nargs="?", choices=["start", "env"], default="start",
                        help="'start' runs the proxy (default); 'env' prints the export lines to use it")
    parser.add_argument("--host", default="127.0.0.1", help="bind address (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--anthropic-upstream", default=DEFAULT_ANTHROPIC_UPSTREAM)
    parser.add_argument("--openai-upstream", default=DEFAULT_OPENAI_UPSTREAM)
    parser.add_argument("-d", "--dialect", action="append", help="comment dialect (repeatable; default: $PROMPT_COMMENTS_DIALECT or 'blocks' = <!-- --> and {# #}; "
                        "use 'default' to also strip // lines)")
    parser.add_argument("--roles", help=f"comma-separated roles to strip (default: {','.join(sorted(DEFAULT_ROLES))})")
    parser.add_argument("--blank-lines", choices=["keep", "comment", "all"])
    parser.add_argument("--allowed-host", action="append", default=[],
                        help="extra Host header value to accept (needed when binding a non-loopback address)")
    parser.add_argument("--dry-run", action="store_true", help="forward requests untouched, log what would change")
    parser.add_argument("--debug-diff", action="store_true", help="log before/after text of changed blocks (contains prompt text!)")
    parser.add_argument("-v", "--verbose", action="store_true")


def run(args: argparse.Namespace) -> int:
    if args.action == "env":
        print(env_exports(args.host, args.port))
        return 0
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="prompt-comments proxy: %(message)s", stream=sys.stderr)
    try:
        policy = StripPolicy.from_env(
            dialect=(args.dialect[0] if args.dialect and len(args.dialect) == 1 else args.dialect),
            roles=frozenset(r.strip() for r in args.roles.split(",") if r.strip()) if args.roles else None,
            blank_lines=args.blank_lines,
        )
        config = ProxyConfig(
            host=args.host, port=args.port,
            anthropic_upstream=args.anthropic_upstream, openai_upstream=args.openai_upstream,
            policy=policy, dry_run=args.dry_run, debug_diff=args.debug_diff,
            allowed_hosts=args.allowed_host,
        )
        server = make_server(config)
    except (ValueError, OSError) as exc:
        print(f"prompt-comments proxy: {exc}", file=sys.stderr)
        return 2

    if not _is_loopback(args.host):
        log.warning("listening on non-loopback address %s: anyone who can reach it can relay "
                    "requests (with their own credentials) to your upstreams", args.host)
    if not policy.enabled:
        log.warning("PROMPT_COMMENTS_DISABLED is set: requests are forwarded unchanged")
    log.info("listening on http://%s:%d%s", args.host, args.port, "  [dry-run]" if args.dry_run else "")
    log.info("  Anthropic -> %s", args.anthropic_upstream)
    log.info("  OpenAI    -> %s", args.openai_upstream)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log.info("shutting down")
    finally:
        server.server_close()
    return 0
