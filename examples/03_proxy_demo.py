"""Run the comment-stripping proxy in-process against a fake upstream and watch it work.

For real use, start it from a shell instead:

    prompt-comments proxy                        # then:
    export ANTHROPIC_BASE_URL=http://127.0.0.1:8787

This demo is fully offline:

    python examples/03_proxy_demo.py
"""

import http.client
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from prompt_comments import StripPolicy
from prompt_comments.proxy import ProxyConfig, make_server


class FakeAnthropic(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        body = self.rfile.read(int(self.headers["Content-Length"]))
        print("upstream received:", json.dumps(json.loads(body), indent=2))
        print("upstream saw x-api-key:", self.headers["x-api-key"])
        reply = b'{"ok": true}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(reply)))
        self.end_headers()
        self.wfile.write(reply)


def serve(server):
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


upstream = serve(HTTPServer(("127.0.0.1", 0), FakeAnthropic))
config = ProxyConfig(
    port=0,
    anthropic_upstream=f"http://127.0.0.1:{upstream.server_port}",
    policy=StripPolicy(),  # default dialect "blocks": <!-- --> and {# #}
)
proxy = serve(make_server(config))

# What Claude Code does: CLAUDE.md text rides along inside the first *user* message.
request = {
    "model": "claude-sonnet-5-5",
    "max_tokens": 32,
    "system": "You are a coding agent. <!-- internal: keep in sync with the eval prompt -->",
    "messages": [{"role": "user", "content": [
        {"type": "text", "text": "# CLAUDE.md\nUse pytest. <!-- why: CI only has pytest -->\n// not a comment on the wire"},
        {"type": "text", "text": "run the tests"},
    ]}],
}
conn = http.client.HTTPConnection("127.0.0.1", proxy.server_port)
conn.request("POST", "/v1/messages", json.dumps(request), {
    "Content-Type": "application/json", "x-api-key": "sk-demo", "anthropic-version": "2023-06-01",
})
print("proxy replied:", conn.getresponse().read().decode())

conn = http.client.HTTPConnection("127.0.0.1", proxy.server_port)
conn.request("GET", "/stats")
print("proxy /stats:", conn.getresponse().read().decode())
