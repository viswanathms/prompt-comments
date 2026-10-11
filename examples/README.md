# Examples

Everything here runs offline (mock transports / a fake upstream), no API key needed.
From the repo root, with the package installed:

| File | Shows |
|---|---|
| [`01_strip_basics.py`](01_strip_basics.py) | `strip_comments`: dialects, `blank_lines`, code-block protection, escaping |
| [`02_sdk_install.py`](02_sdk_install.py) | `install()` / `wrap_client()` / `wrap_sdk_client()` — before/after request bodies, stats |
| [`03_proxy_demo.py`](03_proxy_demo.py) | The proxy cleaning a Claude-Code-shaped request (system + CLAUDE.md in a user block) |
| [`claude-md/`](claude-md) | `CLAUDE.src.md` / `AGENTS.src.md` and their generated outputs (`prompt-comments build`) |

```bash
python examples/01_strip_basics.py
python examples/02_sdk_install.py      # also exercises the real anthropic SDK if installed
python examples/03_proxy_demo.py
cd examples/claude-md && python -m prompt_comments build && python -m prompt_comments build --check
```

## Recipes

**Claude Code / Codex through the proxy**

```bash
prompt-comments proxy --dry-run --debug-diff   # 1. audit: forwards untouched, logs what WOULD change
prompt-comments proxy                          # 2. enable: strips <!-- --> and {# #}
prompt-comments proxy -d default               #    ...or also strip // lines
export ANTHROPIC_BASE_URL=http://127.0.0.1:8787   # in the shell that launches `claude` (API-key login)
curl -s http://127.0.0.1:8787/stats            # counters: requests, modified, bytes saved
```

**One line in your own app**

```python
import prompt_comments.auto     # PROMPT_COMMENTS_DISABLED=1 turns it off without code changes
```

**Keep generated files honest in CI**

```bash
prompt-comments build --check   # exits 1 if CLAUDE.md / AGENTS.md drifted from their *.src.md
```
