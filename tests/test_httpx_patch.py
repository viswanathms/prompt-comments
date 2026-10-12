import asyncio
import importlib
import json

import pytest

import prompt_comments
from prompt_comments import StripPolicy, httpx_patch

POLICY = StripPolicy(dialect="default")
BODY = {"model": "m", "max_tokens": 5, "messages": [{"role": "user", "content": "hi // secret"}]}


@pytest.fixture(autouse=True)
def _clean_install():
    httpx_patch.uninstall()
    yield
    httpx_patch.uninstall()


@pytest.fixture(params=["httpx", "httpx2"])
def lib(request):
    return pytest.importorskip(request.param)


class Recorder:
    def __init__(self, lib):
        self.lib = lib
        self.requests = []

    def __call__(self, request):
        self.requests.append(request)
        return self.lib.Response(200, json={"ok": True})

    @property
    def body(self):
        return json.loads(self.requests[-1].content)

    def client(self):
        return self.lib.Client(transport=self.lib.MockTransport(self))


def test_install_strips_sync_request_and_fixes_content_length(lib):
    rec = Recorder(lib)
    stats = prompt_comments.install(POLICY)
    rec.client().post("https://api.anthropic.com/v1/messages", json=BODY, headers={"x-api-key": "k"})

    assert rec.body["messages"][0]["content"] == "hi"
    sent = rec.requests[-1]
    assert int(sent.headers["content-length"]) == len(sent.content)
    assert sent.headers["x-api-key"] == "k"
    assert stats.snapshot()["modified"] == 1


def test_streaming_requests_are_covered(lib):
    rec = Recorder(lib)
    prompt_comments.install(POLICY)
    with rec.client().stream("POST", "https://api.openai.com/v1/chat/completions", json={
        "messages": [{"role": "user", "content": "a {# x #}"}], "stream": True,
    }) as resp:
        resp.read()
    assert rec.body["messages"][0]["content"] == "a"


def test_async_requests_are_covered(lib):
    rec = Recorder(lib)

    async def run():
        async with lib.AsyncClient(transport=lib.MockTransport(rec)) as c:
            await c.post("https://api.anthropic.com/v1/messages", json=BODY)

    prompt_comments.install(POLICY)
    asyncio.run(run())
    assert rec.body["messages"][0]["content"] == "hi"


def test_non_llm_and_non_json_requests_untouched(lib):
    rec = Recorder(lib)
    prompt_comments.install(POLICY)
    c = rec.client()
    c.post("https://example.com/v1/models", json=BODY)
    assert rec.body == BODY
    c.post("https://api.anthropic.com/v1/messages", content=b"hi // x", headers={"content-type": "text/plain"})
    assert rec.requests[-1].content == b"hi // x"
    c.get("https://api.anthropic.com/v1/messages")
    assert rec.requests[-1].content == b""


def test_content_encoded_body_is_skipped(lib):
    rec = Recorder(lib)
    prompt_comments.install(POLICY)
    raw = json.dumps(BODY).encode()
    rec.client().post("https://api.anthropic.com/v1/messages", content=raw,
                      headers={"content-type": "application/json", "content-encoding": "gzip"})
    assert rec.requests[-1].content == raw


def test_unchanged_body_is_byte_identical(lib):
    rec = Recorder(lib)
    prompt_comments.install(POLICY)
    raw = b'{"messages": [{"role":"user",  "content":"clean"}]}'
    rec.client().post("https://api.anthropic.com/v1/messages", content=raw,
                      headers={"content-type": "application/json"})
    assert rec.requests[-1].content == raw


def test_hosts_filter(lib):
    rec = Recorder(lib)
    prompt_comments.install(POLICY, hosts=["llm.internal"])
    c = rec.client()
    c.post("https://api.anthropic.com/v1/messages", json=BODY)
    assert rec.body == BODY
    c.post("https://llm.internal/v1/messages", json=BODY)
    assert rec.body["messages"][0]["content"] == "hi"


def test_install_is_idempotent_and_uninstall_restores(lib):
    original = lib.Client.send
    prompt_comments.install(POLICY)
    patched = lib.Client.send
    prompt_comments.install(StripPolicy(roles={"system"}))
    assert lib.Client.send is patched and patched is not original
    prompt_comments.uninstall()
    prompt_comments.uninstall()
    assert lib.Client.send is original
    assert not httpx_patch.is_installed()


def test_disabled_env_does_not_patch(lib, monkeypatch):
    monkeypatch.setenv("PROMPT_COMMENTS_DISABLED", "1")
    original = lib.Client.send
    prompt_comments.install(POLICY)
    assert lib.Client.send is original


def test_cleaner_failure_falls_back_to_original(lib, monkeypatch):
    rec = Recorder(lib)
    stats = prompt_comments.install(POLICY)

    def boom(*a, **k):
        raise RuntimeError("bug")

    monkeypatch.setattr(httpx_patch, "clean_request_body", boom)
    rec.client().post("https://api.anthropic.com/v1/messages", json=BODY)
    assert rec.body == BODY
    assert stats.snapshot()["errors"] == 1


def test_wrap_client_is_scoped_to_one_client(lib):
    rec = Recorder(lib)
    wrapped = prompt_comments.wrap_client(rec.client(), POLICY)
    plain = rec.client()
    wrapped.post("https://api.anthropic.com/v1/messages", json=BODY)
    assert rec.body["messages"][0]["content"] == "hi"
    plain.post("https://api.anthropic.com/v1/messages", json=BODY)
    assert rec.body == BODY


def test_wrap_client_rejects_foreign_objects():
    with pytest.raises(TypeError):
        prompt_comments.wrap_client(object())


def test_install_plus_wrap_client_does_not_double_process(lib):
    rec = Recorder(lib)
    stats = prompt_comments.install(POLICY)
    c = prompt_comments.wrap_client(rec.client(), POLICY, stats=stats)
    body = {"messages": [{"role": "user", "content": "keep \\// literal // gone"}]}
    c.post("https://api.anthropic.com/v1/messages", json=body)
    assert rec.body["messages"][0]["content"] == "keep // literal"


# --- real SDKs: they may sit on httpx or httpx2 depending on their version ---------


def _sdk_http_library(sdk):
    base = importlib.import_module(f"{sdk.__name__}._base_client")
    return getattr(base, "httpx2", None) or getattr(base, "httpx")


def test_real_anthropic_sdk_smoke_with_global_install():
    anthropic = pytest.importorskip("anthropic")
    lib = _sdk_http_library(anthropic)
    rec = Recorder(lib)

    def handler(request):
        rec.requests.append(request)
        return lib.Response(200, json={
            "id": "m", "type": "message", "role": "assistant", "model": "m", "stop_reason": "end_turn",
            "content": [{"type": "text", "text": "ok"}], "usage": {"input_tokens": 1, "output_tokens": 1},
        })

    prompt_comments.install(POLICY)
    client = anthropic.Anthropic(api_key="k", http_client=lib.Client(transport=lib.MockTransport(handler)))
    client.messages.create(model="m", max_tokens=5, system="sys // x",
                           messages=[{"role": "user", "content": "hi <!-- c -->"}])
    assert rec.body["system"] == "sys"
    assert rec.body["messages"][0]["content"] == "hi"


def test_real_openai_sdk_smoke_with_wrap_sdk_client():
    openai = pytest.importorskip("openai")
    lib = _sdk_http_library(openai)
    rec = Recorder(lib)

    def handler(request):
        rec.requests.append(request)
        return lib.Response(200, json={
            "id": "c", "object": "chat.completion", "created": 1, "model": "m",
            "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": "ok"}}],
        })

    client = openai.OpenAI(api_key="k", http_client=lib.Client(transport=lib.MockTransport(handler)))
    prompt_comments.wrap_sdk_client(client, POLICY)
    client.chat.completions.create(model="m", messages=[{"role": "user", "content": "hi // x"}])
    assert rec.body["messages"][0]["content"] == "hi"
