import copy
import json

import pytest

from prompt_comments.payloads import (
    ANTHROPIC,
    OPENAI_CHAT,
    OPENAI_RESPONSES,
    clean_payload,
    clean_request_body,
    detect_kind,
)
from prompt_comments.policy import Stats, StripPolicy

POLICY = StripPolicy(dialect="default")


@pytest.mark.parametrize(
    "path,kind",
    [
        ("/v1/messages", ANTHROPIC),
        ("/v1/messages/count_tokens", ANTHROPIC),
        ("/gateway/v1/messages", ANTHROPIC),
        ("/v1/chat/completions", OPENAI_CHAT),
        ("/openai/deployments/gpt/chat/completions", OPENAI_CHAT),
        ("/v1/responses", OPENAI_RESPONSES),
        ("/v1/threads/t1/messages", None),
        ("/v1/models", None),
        ("/v1/embeddings", None),
    ],
)
def test_detect_kind(path, kind):
    assert detect_kind(path) == kind


def _anthropic_body():
    return {
        "model": "claude-x",
        "max_tokens": 10,
        "system": [
            {"type": "text", "text": "Be brief. // internal note", "cache_control": {"type": "ephemeral"}},
            {"type": "text", "text": "plain"},
        ],
        "messages": [
            {"role": "user", "content": [
                {"type": "text", "text": "<system-reminder>\nrules <!-- hidden -->\n</system-reminder>"},
                {"type": "image", "source": {"type": "base64", "data": "// not text"}},
            ]},
            {"role": "assistant", "content": [{"type": "text", "text": "I said // this"}]},
            {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "t", "content": "x // keep"},
            ]},
            {"role": "user", "content": "hi {# drop #}"},
        ],
        "tools": [{"name": "t", "description": "// keep"}],
    }


def test_anthropic_strips_system_and_user_text_only():
    body = _anthropic_body()
    original = copy.deepcopy(body)
    out, n = clean_payload(ANTHROPIC, body, POLICY)

    assert body == original  # input never mutated
    assert n == 3
    assert out["system"][0] == {"type": "text", "text": "Be brief.", "cache_control": {"type": "ephemeral"}}
    assert out["system"][1] == {"type": "text", "text": "plain"}
    assert out["messages"][0]["content"][0]["text"] == "<system-reminder>\nrules\n</system-reminder>"
    assert out["messages"][0]["content"][1] == original["messages"][0]["content"][1]
    assert out["messages"][1] == original["messages"][1]  # assistant untouched
    assert out["messages"][2] == original["messages"][2]  # tool_result untouched
    assert out["messages"][3]["content"] == "hi"
    assert out["tools"] == original["tools"]


def test_anthropic_string_system():
    out, n = clean_payload(ANTHROPIC, {"system": "a // b", "messages": []}, POLICY)
    assert (out["system"], n) == ("a", 1)


def test_unchanged_payload_returns_same_object():
    body = {"model": "m", "messages": [{"role": "user", "content": "hello https://x.io"}]}
    out, n = clean_payload(ANTHROPIC, body, POLICY)
    assert out is body and n == 0


def test_block_that_would_become_empty_is_left_alone():
    body = {"messages": [{"role": "user", "content": [{"type": "text", "text": "// only a comment"}]}]}
    out, n = clean_payload(ANTHROPIC, body, POLICY)
    assert out is body and n == 0


def test_roles_option_restricts_stripping():
    body = {"system": "a // b", "messages": [{"role": "user", "content": "c // d"}]}
    out, _ = clean_payload(ANTHROPIC, body, StripPolicy(dialect="default", roles={"system"}))
    assert out["system"] == "a" and out["messages"][0]["content"] == "c // d"


def test_openai_chat():
    body = {
        "model": "m",
        "messages": [
            {"role": "system", "content": "sys // x"},
            {"role": "developer", "content": [{"type": "text", "text": "dev {# x #}"}]},
            {"role": "user", "content": [
                {"type": "text", "text": "u <!-- x -->"},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,//AA"}},
            ]},
            {"role": "assistant", "content": "a // keep"},
            {"role": "tool", "tool_call_id": "1", "content": "// keep"},
            {"role": "assistant", "content": None, "tool_calls": []},
        ],
    }
    original = copy.deepcopy(body)
    out, n = clean_payload(OPENAI_CHAT, body, POLICY)
    assert body == original and n == 3
    assert out["messages"][0]["content"] == "sys"
    assert out["messages"][1]["content"][0]["text"] == "dev"
    assert out["messages"][2]["content"][0]["text"] == "u"
    assert out["messages"][2]["content"][1] == original["messages"][2]["content"][1]
    assert out["messages"][3:] == original["messages"][3:]


def test_openai_responses():
    body = {
        "model": "m",
        "instructions": "be nice // x",
        "input": [
            {"role": "user", "content": [{"type": "input_text", "text": "q {# c #}"}]},
            {"role": "assistant", "content": [{"type": "output_text", "text": "// keep"}]},
            {"type": "function_call_output", "call_id": "1", "output": "// keep"},
        ],
    }
    original = copy.deepcopy(body)
    out, n = clean_payload(OPENAI_RESPONSES, body, POLICY)
    assert body == original and n == 2
    assert out["instructions"] == "be nice"
    assert out["input"][0]["content"][0]["text"] == "q"
    assert out["input"][1:] == original["input"][1:]


def test_openai_responses_string_input():
    out, n = clean_payload(OPENAI_RESPONSES, {"input": "hi // x"}, POLICY)
    assert (out["input"], n) == ("hi", 1)


def test_clean_request_body_roundtrip_and_stats():
    stats = Stats()
    raw = json.dumps({"messages": [{"role": "user", "content": "héllo // x"}]}).encode()
    new = clean_request_body("/v1/messages", raw, POLICY, stats)
    assert json.loads(new) == {"messages": [{"role": "user", "content": "héllo"}]}
    snap = stats.snapshot()
    assert (snap["requests"], snap["modified"], snap["blocks_changed"]) == (1, 1, 1)
    assert snap["bytes_in"] == len(raw) and snap["bytes_out"] == len(new)


@pytest.mark.parametrize(
    "path,raw",
    [
        ("/v1/models", b'{"messages":[{"role":"user","content":"a // b"}]}'),  # not an LLM path
        ("/v1/messages", b"not json"),
        ("/v1/messages", b"[1, 2]"),
        ("/v1/messages", b""),
        ("/v1/messages", b'{"messages":[{"role":"user","content":"clean"}]}'),
    ],
)
def test_clean_request_body_passthrough_cases(path, raw):
    assert clean_request_body(path, raw, POLICY, Stats()) is None


def test_clean_request_body_disabled_and_oversized():
    raw = b'{"messages":[{"role":"user","content":"a // b"}]}'
    assert clean_request_body("/v1/messages", raw, StripPolicy(enabled=False)) is None
    assert clean_request_body("/v1/messages", raw, StripPolicy(max_body_bytes=5)) is None


def test_clean_request_body_fails_open(monkeypatch):
    stats = Stats()

    def boom(*a, **k):
        raise RuntimeError("bug")

    monkeypatch.setattr("prompt_comments.payloads.clean_payload", boom)
    raw = b'{"messages":[{"role":"user","content":"a // b"}]}'
    assert clean_request_body("/v1/messages", raw, POLICY, stats) is None
    assert stats.snapshot()["errors"] == 1


def test_policy_from_env():
    p = StripPolicy.from_env(
        {
            "PROMPT_COMMENTS_DISABLED": "1",
            "PROMPT_COMMENTS_DIALECT": "markdown, python",
            "PROMPT_COMMENTS_ROLES": "system",
            "PROMPT_COMMENTS_BLANK_LINES": "all",
        }
    )
    assert (p.enabled, p.dialect, p.roles, p.blank_lines) == (False, ["markdown", "python"], {"system"}, "all")
    assert StripPolicy.from_env({}).enabled is True


def test_wire_default_strips_block_comments_but_not_double_slash():
    # Third-party instruction text often mentions `//` in prose ("write `// note: ...`");
    # the wire-level default must not treat that as a comment.
    body = {"system": "Mark it: // lean-ctx: <ceiling> <!-- internal -->", "messages": []}
    out, n = clean_payload(ANTHROPIC, body, StripPolicy())
    assert n == 1 and out["system"] == "Mark it: // lean-ctx: <ceiling>"


def test_kill_switch_beats_explicit_policy(monkeypatch):
    raw = b'{"messages":[{"role":"user","content":"a // b"}]}'
    assert clean_request_body("/v1/messages", raw, POLICY) is not None
    monkeypatch.setenv("PROMPT_COMMENTS_DISABLED", "1")
    assert clean_request_body("/v1/messages", raw, POLICY) is None


def test_policy_rejects_bad_values():
    with pytest.raises(ValueError):
        StripPolicy(dialect="nope")
    with pytest.raises(ValueError):
        StripPolicy(blank_lines="nope")
