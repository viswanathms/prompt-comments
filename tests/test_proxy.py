import gzip
import http.client
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler

import pytest

from prompt_comments.policy import StripPolicy
from prompt_comments.proxy import ProxyConfig, ProxyServer, env_exports, make_server

BODY = {"model": "m", "messages": [{"role": "user", "content": "hi // secret"}]}


class FakeUpstream:
    """Records requests; behaviour is chosen per request with the x-test-mode header."""

    def __init__(self, name):
        self.name = name
        self.requests = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a):
                pass

            def _serve(self):
                length = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(length) if length else b""
                outer.requests.append({
                    "method": self.command, "path": self.path, "headers": dict(self.headers.items()), "body": body,
                })
                mode = self.headers.get("x-test-mode", "echo")
                if mode == "stream":
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream")
                    self.send_header("Transfer-Encoding", "chunked")
                    self.end_headers()
                    for part in (b"data: one\n\n", b"data: two\n\n"):
                        self.wfile.write(b"%x\r\n%s\r\n" % (len(part), part))
                        self.wfile.flush()
                        time.sleep(0.6)
                    self.wfile.write(b"0\r\n\r\n")
                elif mode == "429":
                    payload = b'{"error":"slow down"}'
                    self.send_response(429)
                    self.send_header("retry-after", "7")
                    self.send_header("Content-Length", str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)
                else:
                    payload = json.dumps({"upstream": outer.name}).encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(payload)))
                    self.end_headers()
                    if self.command != "HEAD":
                        self.wfile.write(payload)

            do_GET = do_POST = _serve

        self.server = ProxyServer(("127.0.0.1", 0), Handler)  # quiet on dropped keep-alives
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def anthropic_up():
    up = FakeUpstream("anthropic")
    yield up
    up.close()


@pytest.fixture
def openai_up():
    up = FakeUpstream("openai")
    yield up
    up.close()


@pytest.fixture
def make_proxy(anthropic_up, openai_up):
    servers = []

    def factory(**kwargs):
        cfg = ProxyConfig(
            port=0,
            anthropic_upstream=kwargs.pop("anthropic_upstream", anthropic_up.url),
            openai_upstream=kwargs.pop("openai_upstream", openai_up.url),
            policy=kwargs.pop("policy", StripPolicy(dialect="default")),
            **kwargs,
        )
        server = make_server(cfg)
        threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True).start()
        servers.append(server)
        return cfg, server.server_port

    yield factory
    for s in servers:
        s.shutdown()
        s.server_close()


def request(port, method, path, body=None, headers=None, host=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    hdrs = dict(headers or {})
    if host is not None:
        hdrs["Host"] = host
    conn.request(method, path, body=body, headers=hdrs)
    resp = conn.getresponse()
    return conn, resp


def post_json(port, path, payload, headers=None):
    hdrs = {"Content-Type": "application/json", **(headers or {})}
    conn, resp = request(port, "POST", path, json.dumps(payload).encode(), hdrs)
    data = resp.read()
    conn.close()
    return resp, data


def test_cleans_body_and_forwards_headers(make_proxy, anthropic_up):
    cfg, port = make_proxy()
    resp, data = post_json(port, "/v1/messages?beta=true", BODY, {
        "x-api-key": "sk-test", "anthropic-version": "2023-06-01", "anthropic-beta": "a,b",
        "Keep-Alive": "5", "X-Custom": "1",
    })
    assert resp.status == 200 and json.loads(data) == {"upstream": "anthropic"}

    got = anthropic_up.requests[-1]
    assert got["path"] == "/v1/messages?beta=true"
    assert json.loads(got["body"])["messages"][0]["content"] == "hi"
    assert int(got["headers"]["Content-Length"]) == len(got["body"])
    h = {k.lower(): v for k, v in got["headers"].items()}
    assert h["x-api-key"] == "sk-test" and h["anthropic-beta"] == "a,b" and h["x-custom"] == "1"
    assert "keep-alive" not in h
    assert h["host"] == f"127.0.0.1:{anthropic_up.server.server_port}"
    assert cfg.stats.snapshot()["modified"] == 1


def test_unchanged_body_is_forwarded_byte_identical(make_proxy, anthropic_up):
    _, port = make_proxy()
    raw = b'{"messages": [{"role":"user",  "content":"clean"}]}'
    conn, resp = request(port, "POST", "/v1/messages", raw, {"Content-Type": "application/json"})
    resp.read()
    assert anthropic_up.requests[-1]["body"] == raw


def test_routing_by_path_and_headers(make_proxy, anthropic_up, openai_up):
    _, port = make_proxy()
    post_json(port, "/v1/chat/completions", {"messages": []})
    assert len(openai_up.requests) == 1 and not anthropic_up.requests
    conn, resp = request(port, "GET", "/v1/models", headers={"anthropic-version": "2023-06-01"})
    resp.read()
    assert anthropic_up.requests[-1]["path"] == "/v1/models"
    conn, resp = request(port, "GET", "/v1/models")
    assert json.loads(resp.read()) == {"upstream": "openai"}


def test_upstream_path_prefix(make_proxy, anthropic_up):
    _, port = make_proxy(anthropic_upstream=anthropic_up.url + "/gateway/")
    post_json(port, "/v1/messages", BODY)
    assert anthropic_up.requests[-1]["path"] == "/gateway/v1/messages"


def test_streaming_is_not_buffered(make_proxy):
    _, port = make_proxy()
    start = time.monotonic()
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    conn.request("POST", "/v1/messages", json.dumps(BODY).encode(),
                 {"Content-Type": "application/json", "x-test-mode": "stream"})
    resp = conn.getresponse()
    first = resp.read1(1024)
    first_at = time.monotonic() - start
    rest = resp.read()
    assert b"one" in first and b"two" in first + rest
    assert first_at < 0.5  # arrived long before the upstream finished (~1.2 s)
    conn.close()


def test_error_status_and_headers_pass_through(make_proxy):
    _, port = make_proxy()
    resp, data = post_json(port, "/v1/messages", BODY, {"x-test-mode": "429"})
    assert resp.status == 429
    assert resp.getheader("retry-after") == "7"
    assert json.loads(data) == {"error": "slow down"}


def test_foreign_host_header_is_rejected(make_proxy, anthropic_up):
    _, port = make_proxy()
    conn, resp = request(port, "POST", "/v1/messages", json.dumps(BODY).encode(), host="evil.example")
    assert resp.status == 421
    assert not anthropic_up.requests


def test_chunked_request_body(make_proxy, anthropic_up):
    _, port = make_proxy()
    payload = json.dumps(BODY).encode()
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    conn.request("POST", "/v1/messages", body=iter([payload[:10], payload[10:]]),
                 headers={"Content-Type": "application/json", "Transfer-Encoding": "chunked"}, encode_chunked=True)
    assert conn.getresponse().status == 200
    assert json.loads(anthropic_up.requests[-1]["body"])["messages"][0]["content"] == "hi"


def test_oversized_and_content_encoded_bodies_pass_through(make_proxy, anthropic_up):
    _, port = make_proxy(policy=StripPolicy(dialect="default", max_body_bytes=10))
    raw = json.dumps(BODY).encode()
    post_json(port, "/v1/messages", BODY)
    assert anthropic_up.requests[-1]["body"] == raw

    _, port = make_proxy()
    zipped = gzip.compress(raw)
    conn, resp = request(port, "POST", "/v1/messages", zipped,
                         {"Content-Type": "application/json", "Content-Encoding": "gzip"})
    resp.read()
    assert anthropic_up.requests[-1]["body"] == zipped


def test_dry_run_forwards_original_but_counts(make_proxy, anthropic_up):
    cfg, port = make_proxy(dry_run=True)
    post_json(port, "/v1/messages", BODY)
    assert json.loads(anthropic_up.requests[-1]["body"]) == BODY
    assert cfg.stats.snapshot()["modified"] == 1


def test_upstream_down_returns_provider_shaped_502(make_proxy, anthropic_up, openai_up):
    dead = FakeUpstream("dead")
    dead_url = dead.url
    dead.close()
    _, port = make_proxy(anthropic_upstream=dead_url, openai_upstream=dead_url)
    resp, data = post_json(port, "/v1/messages", BODY)
    assert resp.status == 502 and json.loads(data)["type"] == "error"
    resp, data = post_json(port, "/v1/chat/completions", {"messages": []})
    assert resp.status == 502 and json.loads(data)["error"]["code"] == "upstream_unreachable"


def test_tls_verification_failure_gets_an_actionable_502(make_proxy, monkeypatch):
    import ssl

    from prompt_comments import proxy as proxy_module

    def fail(self):
        raise ssl.SSLCertVerificationError("CERTIFICATE_VERIFY_FAILED")

    monkeypatch.setattr(proxy_module._Upstream, "connect", fail)
    _, port = make_proxy()
    resp, data = post_json(port, "/v1/messages", BODY)
    message = json.loads(data)["error"]["message"]
    assert resp.status == 502
    assert "SSLCertVerificationError" in message and "Install Certificates.command" in message


def test_ssl_context_falls_back_to_certifi_when_no_system_roots(monkeypatch):
    import ssl
    import types

    from prompt_comments import proxy as proxy_module

    loaded = []

    class FakeCtx:
        def cert_store_stats(self):
            return {"x509_ca": 0}

        def load_verify_locations(self, path):
            loaded.append(path)

    monkeypatch.setattr(proxy_module, "_ssl_ctx", None)
    monkeypatch.setattr(ssl, "create_default_context", lambda: FakeCtx())
    monkeypatch.setitem(__import__("sys").modules, "certifi", types.SimpleNamespace(where=lambda: "/fake/cacert.pem"))
    assert isinstance(proxy_module._ssl_context(), FakeCtx)
    assert loaded == ["/fake/cacert.pem"]
    monkeypatch.setattr(proxy_module, "_ssl_ctx", None)  # don't leak the fake into other tests


def test_health_and_stats_endpoints(make_proxy):
    _, port = make_proxy()
    post_json(port, "/v1/messages", BODY)
    conn, resp = request(port, "GET", "/health")
    assert json.loads(resp.read()) == {"status": "ok"}
    conn, resp = request(port, "GET", "/stats")
    stats = json.loads(resp.read())
    assert stats["modified"] == 1 and stats["dry_run"] is False


def test_concurrent_requests(make_proxy, anthropic_up):
    cfg, port = make_proxy()

    def one(i):
        resp, _ = post_json(port, "/v1/messages", {"messages": [{"role": "user", "content": f"q{i} // x"}]})
        return resp.status

    with ThreadPoolExecutor(8) as pool:
        assert set(pool.map(one, range(32))) == {200}
    assert cfg.stats.snapshot()["modified"] == 32
    sent = sorted(json.loads(r["body"])["messages"][0]["content"] for r in anthropic_up.requests)
    assert sent == sorted(f"q{i}" for i in range(32))


def test_upstream_url_validation():
    with pytest.raises(ValueError):
        ProxyConfig(anthropic_upstream="http://api.example.com")  # plain http, non-loopback
    with pytest.raises(ValueError):
        ProxyConfig(openai_upstream="ftp://x")


def test_env_exports():
    assert env_exports("127.0.0.1", 8787) == (
        "export ANTHROPIC_BASE_URL=http://127.0.0.1:8787\nexport OPENAI_BASE_URL=http://127.0.0.1:8787/v1"
    )
