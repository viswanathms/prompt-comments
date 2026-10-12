"""Strip comments from every LLM request your Python process sends.

Offline demo: requests go to a mock transport that prints what would have hit the wire.
If the `anthropic` or `openai` SDK is installed, the real SDKs are exercised too.

    python examples/02_sdk_install.py
"""

import json

try:  # the newest Anthropic/OpenAI SDKs use httpx2; older ones use httpx
    import httpx2 as http
except ImportError:
    import httpx as http

import prompt_comments
from prompt_comments import StripPolicy

SYSTEM = "Be concise. <!-- v3: shortened after the March eval -->"
USER = "Summarise the ticket. {# the customer is VIP #}"


def show(request: "http.Request") -> "http.Response":
    body = json.loads(request.content)
    print(json.dumps(body, indent=2))
    return http.Response(200, json={})


def client():
    return http.Client(transport=http.MockTransport(show))


print("== before install(): comments go out as written ==")
client().post("https://api.anthropic.com/v1/messages", json={
    "model": "claude-sonnet-5-5", "max_tokens": 64, "system": SYSTEM,
    "messages": [{"role": "user", "content": USER}],
})

stats = prompt_comments.install()  # global: every httpx / httpx2 client in this process
print("\n== after install(): same call, comments removed ==")
client().post("https://api.anthropic.com/v1/messages", json={
    "model": "claude-sonnet-5-5", "max_tokens": 64, "system": SYSTEM,
    "messages": [
        {"role": "user", "content": USER},
        {"role": "assistant", "content": "Sure // assistant turns are never touched"},
    ],
})
print("\nstats:", stats.snapshot())
prompt_comments.uninstall()

print("\n== wrap just one client, strip '//' lines too, system prompt only ==")
policy = StripPolicy(dialect="default", roles={"system"})
scoped = prompt_comments.wrap_client(client(), policy)
scoped.post("https://api.openai.com/v1/chat/completions", json={"model": "gpt", "messages": [
    {"role": "system", "content": "Be formal. // tone note"},
    {"role": "user", "content": "hello // user text kept: roles={'system'}"},
]})

try:
    import anthropic
except ImportError:
    print("\n(install `anthropic` to see the real SDK path)")
else:
    print("\n== real Anthropic SDK, wrapped client ==")

    def fake_reply(request):
        print("SDK sent system =", json.loads(request.content)["system"])
        return http.Response(200, json={
            "id": "m", "type": "message", "role": "assistant", "model": "m", "stop_reason": "end_turn",
            "content": [{"type": "text", "text": "ok"}], "usage": {"input_tokens": 1, "output_tokens": 1},
        })

    sdk = anthropic.Anthropic(api_key="demo", http_client=http.Client(transport=http.MockTransport(fake_reply)))
    prompt_comments.wrap_sdk_client(sdk)
    sdk.messages.create(model="m", max_tokens=8, system=SYSTEM, messages=[{"role": "user", "content": "hi"}])
