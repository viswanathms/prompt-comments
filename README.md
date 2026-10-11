# prompt-comments

[![CI](https://github.com/viswanathms/prompt-comments/actions/workflows/ci.yml/badge.svg)](https://github.com/viswanathms/prompt-comments/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/prompt-comments.svg)](https://pypi.org/project/prompt-comments/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Write comments in your AI prompts. Strip them before they reach the model.

Prompts live in Markdown files, Jinja templates, YAML configs, plain
`.txt` files — but none of those give you a way to leave a note for
your future self ("why is this instruction here?", "TODO: tighten
this up") without the note leaking into the actual text sent to the
model. `prompt-comments` strips comments in whatever format your
prompt already uses, right before you hand the text to your LLM SDK
of choice.

```python
from prompt_comments import strip_comments

prompt = """
You are a helpful support assistant. {# keep tone friendly, not robotic #}
Always answer in the user's language. <!-- TODO: revisit for RTL languages -->
"""

strip_comments(prompt)
# "\nYou are a helpful support assistant.\nAlways answer in the user's language.\n"
```

## Install

```bash
pip install prompt-comments
```

## Usage

### Strip comments from a string

```python
from prompt_comments import strip_comments

strip_comments("Summarize this. {# only for the 'concise' variant #}")
# "Summarize this."
```

By default, `strip_comments` removes a small set of comment styles
that are unlikely to collide with real prompt text: Jinja-style block
comments (`{# ... #}`), HTML/Markdown block comments (`<!-- ... -->`),
and `//` line comments. Pick a different (or additional) dialect for
formats with their own conventions:

```python
strip_comments(open("system_prompt.yaml").read(), dialect="yaml")

# Combine multiple dialects
strip_comments(text, dialect=["jinja", "yaml"])
```

### Load a prompt straight from a file

`load_prompt` reads a file and infers the right dialect from its
extension automatically (`.j2`/`.jinja2` → Jinja, `.md` → Markdown,
`.yaml` → YAML, ...):

```python
from prompt_comments import load_prompt

system_prompt = load_prompt("prompts/system.md")
```

Override the inferred dialect if needed:

```python
load_prompt("prompts/system.txt", dialect="yaml")
```

### Command line

```bash
prompt-comments prompts/system.md            # auto-detects dialect from extension
prompt-comments prompts/system.txt -d yaml    # force a dialect
cat prompt.txt | prompt-comments -d jinja     # read from stdin
prompt-comments --list-dialects
python -m prompt_comments prompts/system.md   # same thing
```

### Escaping a literal marker

Prefix a line-comment marker with `\` to keep it literally instead of
treating it as a comment:

```python
strip_comments(r"The meeting room is \#3 today", dialect="yaml")
# "The meeting room is #3 today"
```

### Dropping now-empty lines

Comments that occupied a whole line leave a blank line behind by
default. Use `blank_lines` to control that:

```python
text = "keep\n\n// only a comment\nkeep too"
strip_comments(text, blank_lines="keep")     # default: "keep\n\n\nkeep too"
strip_comments(text, blank_lines="comment")  # drop only lines a comment emptied: "keep\n\nkeep too"
strip_comments(text, blank_lines="all")      # drop every blank line: "keep\nkeep too"
```

`strip_blank_lines=True` is still accepted and means `blank_lines="all"`.

### Code is left alone

Fenced code blocks (```` ``` ```` / `~~~`) and `` `inline code` `` are never
stripped, so a code sample in a prompt keeps its own `// comments`. Pass
`protect_code=False` (CLI: `--no-protect-code`) for the old behaviour.

## Strip comments from every LLM call, automatically

Calling `strip_comments` yourself works for prompts you control. For
everything else — SDK calls deep in a framework, `CLAUDE.md` /
`AGENTS.md` read by a coding agent — pick one of three layers. What gets
cleaned is always the same: **system / developer prompts and user text**.
Assistant turns, tool calls, tool results, images and documents are never
touched, and a text block that would end up empty is left as it was.

On the wire only **block comments** are stripped by default — `<!-- ... -->`
and `{# ... #}` (the `blocks` dialect). The request contains instructions you
didn't write (a coding agent's own system prompt, for instance, tells the
model to write comments like `// note: ...`), so a `//` in prose is not
assumed to be a comment. Opt in to `//` line comments with
`StripPolicy(dialect="default")` / `PROMPT_COMMENTS_DIALECT=default` /
`proxy -d default`. `build` (layer 3) processes files you wrote and
defaults to `default`.

### 1. In your Python process

```python
import prompt_comments
prompt_comments.install()      # or simply: import prompt_comments.auto
```

This wraps `send` on `httpx` (and its fork `httpx2`, which the newest
Anthropic and OpenAI SDKs use), so the Anthropic and OpenAI SDKs — and
LiteLLM, LangChain, and anything else built on them — are covered, sync
or async, streaming or not. Recognised endpoints: Anthropic `/v1/messages`
(+ `count_tokens`), OpenAI `/chat/completions` and `/responses`.

Prefer not to patch globally? Wrap one client:

```python
import anthropic, httpx2   # `httpx` for older SDK versions
from prompt_comments import wrap_client, wrap_sdk_client

client = anthropic.Anthropic(http_client=wrap_client(httpx2.Client()))
# or, for a client you already have:
wrap_sdk_client(client)
```

Options: `install(policy=StripPolicy(dialect="default", roles={"system"}), hosts=["llm.internal"])`.
Environment variables work too (`PROMPT_COMMENTS_DISABLED=1` switches
everything off; `PROMPT_COMMENTS_DIALECT`, `PROMPT_COMMENTS_ROLES`,
`PROMPT_COMMENTS_BLANK_LINES`, `PROMPT_COMMENTS_HOSTS`).

### 2. A local proxy, for tools you don't control (Claude Code, Codex, ...)

```bash
prompt-comments proxy                       # listens on 127.0.0.1:8787
prompt-comments proxy env                   # prints the exports below
export ANTHROPIC_BASE_URL=http://127.0.0.1:8787
export OPENAI_BASE_URL=http://127.0.0.1:8787/v1
claude        # its requests — CLAUDE.md included — now arrive comment-free
```

Claude Code sends your `CLAUDE.md` as text inside the first *user*
message, which is why user text is in scope by default. The proxy has no
dependencies, streams responses back untouched, forwards every header
(your API key is only ever relayed, never stored or logged), binds to
loopback only and rejects foreign `Host` headers. If anything goes wrong
while cleaning, the original request is forwarded unchanged.

Audit before you trust it: `prompt-comments proxy --dry-run --debug-diff`
forwards requests untouched and logs what *would* be stripped (the diff
contains prompt text — don't share those logs). `GET /stats` shows
counters. Widen with `-d default` (also strips `//` lines) or narrow with
`--roles system,developer`.

Claude Pro/Max logins may not work with a custom `ANTHROPIC_BASE_URL`;
use an API key. Nothing here edits your Claude Code settings or shell
profile — you set the variables yourself.

### 3. Write CLAUDE.md with comments, ship it without

```bash
prompt-comments build                # CLAUDE.src.md -> CLAUDE.md, AGENTS.src.md -> AGENTS.md, ...
prompt-comments build --check        # CI / pre-commit: exit 1 if an output is stale
prompt-comments build --watch
```

Edit `CLAUDE.src.md` as much as you like; commit both files. Works with
every tool, no runtime pieces. A pre-commit hook is provided:

```yaml
repos:
  - repo: https://github.com/viswanathms/prompt-comments
    rev: v0.2.0
    hooks:
      - id: prompt-comments-build
```

`@imports` inside `CLAUDE.md` are not followed — give imported files a
`.src.md` source too. Auto-discovery looks for `*.src.md`, `*.src.mdc`
and `*.src.txt`; pass paths explicitly for anything else.

## Supported dialects

| Dialect | Line comments | Block comments |
|---|---|---|
| `default` | `//` | `{# #}`, `<!-- -->` |
| `blocks` | — | `{# #}`, `<!-- -->` (the proxy / `install()` default) |
| `jinja` / `jinja2` | — | `{# #}` |
| `django` | — | `{# #}`, `{% comment %}...{% endcomment %}` |
| `liquid` | — | `{% comment %}...{% endcomment %}` |
| `handlebars` / `mustache` | — | `{{! }}`, `{{!-- --}}` |
| `markdown` / `html` / `xml` | — | `<!-- -->` |
| `yaml` / `toml` / `env` | `#` | — |
| `ini` | `#`, `;` | — |
| `json5` / `jsonc` | `//` | `/* */` |
| `python` | `#` | — |
| `shell` / `bash` / `sh` / `zsh` | `#` | — |
| `sql` | `--` | `/* */` |
| `latex` | `%` | — |
| `c` / `js` / `ts` / `go` / `rust` / `java` / `csharp` / ... | `//` | `/* */` |
| `all` | every marker above | every block style above |

Run `prompt-comments --list-dialects` (or `prompt_comments.list_dialects()`) for the exact, current list.

Dialects can be combined by passing a list, e.g. `dialect=["yaml", "jinja"]`.

## A note on false positives

Comment stripping here is regex-based, not a full parser for every
format. A line-comment marker only starts a comment when it's at the
start of a line or preceded by whitespace (this is why
`https://example.com` survives the `//` marker: the `//` is preceded
by `:`, not whitespace). It is still a heuristic — e.g. `# Heading`
in a Markdown file *would* be stripped if you opted into the `yaml`
or `python` dialect (which treat `#` as a comment marker) on that
text. Stick to `default`/`markdown`/`jinja`-style dialects for prose
prompts with literal `#`, `--`, or `%` characters, or escape the
character with a backslash where it must be kept literally.

The same applies to unfenced code pasted into a user message, and to
prose that mentions comment syntax: under the `default` dialect a line
like `x = 1  // note` outside a code fence is a comment. That is why the
wire layers (proxy, `install()`) default to the `blocks` dialect, which
only knows `<!-- -->` and `{# #}`. Check what a given tool sends with
`proxy --dry-run --debug-diff` before widening it.

Stripping is deterministic — the same text always produces the same
output — so provider prompt caching keeps working. It is not strictly
idempotent: an escape such as `\//` is consumed by the first pass, so
don't run two layers (e.g. `build` *and* the proxy) over text that
relies on escapes.

## Development

```bash
pip install -e ".[dev]"            # add ,sdk-tests to also exercise the real Anthropic/OpenAI SDKs
pytest
```

## License

MIT — see [LICENSE](LICENSE).
