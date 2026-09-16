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
default. Pass `strip_blank_lines=True` to drop them instead:

```python
strip_comments("keep\n// only a comment\nkeep too", dialect="c", strip_blank_lines=True)
# "keep\nkeep too"
```

## Supported dialects

| Dialect | Line comments | Block comments |
|---|---|---|
| `default` | `//` | `{# #}`, `<!-- -->` |
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

## Development

```bash
pip install -e ".[dev]"
pytest
```

## License

MIT — see [LICENSE](LICENSE).
