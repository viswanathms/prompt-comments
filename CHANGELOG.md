# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [0.2.0] - Unreleased

### Added
- **Automatic stripping for LLM calls.** `prompt_comments.install()` /
  `import prompt_comments.auto` wrap `httpx` and `httpx2` (used by the Anthropic
  and OpenAI SDKs, LiteLLM, LangChain, ...) so system/developer prompts and user
  text lose their comments before the request is sent. `wrap_client()` and
  `wrap_sdk_client()` do the same for a single client.
- **`prompt-comments proxy`** — a dependency-free local HTTP proxy that strips
  comments from Anthropic and OpenAI requests on the wire (e.g. the CLAUDE.md /
  AGENTS.md text Claude Code and Codex send). Streams responses untouched,
  fails open, loopback-only, `--dry-run` / `--debug-diff` for auditing, `/health`
  and `/stats` endpoints, `proxy env` prints the `*_BASE_URL` exports.
- **`prompt-comments build`** — generate `CLAUDE.md` / `AGENTS.md` from
  `*.src.md` sources, with `--check`, `--watch`, `--banner`, and a
  `.pre-commit-hooks.yaml`.
- `StripPolicy`, `Stats`, `PROMPT_COMMENTS_*` environment variables and the
  `PROMPT_COMMENTS_DISABLED=1` kill switch (wins over any explicit policy).
- `blocks` dialect (`{# #}` and `<!-- -->` only). It is the default for the proxy
  and `install()`: the wire contains third-party instructions (e.g. a coding
  agent's system prompt) where a `//` in prose is not a comment. `-d default`
  opts in to `//` lines; `build` keeps `default`.
- `blank_lines="keep" | "comment" | "all"`: `"comment"` removes only lines a
  comment emptied and keeps your paragraph breaks.
- `python -m prompt_comments`.
- Extras: `httpx`, `sdk-tests`.

### Changed
- **Behaviour change:** fenced code blocks and `` `inline code` `` are now
  protected from stripping by default (`protect_code=True`; CLI
  `--no-protect-code` restores the old behaviour). Previously `` `a // b` ``
  became `` `a `` and comments inside fences were removed.
- Text without any comment marker is returned as the same `str` object.
- Trailing whitespace is now trimmed on every line of text that contained a comment
  (previously only when a line comment was present).
- Single-sourced the package version (`__version__`); `pyproject.toml` reads it.

### Fixed
- CRLF line endings are preserved (a line comment used to swallow the `\r`).
  The CLI and `load_prompt` also no longer convert CRLF to LF when reading files.
- `load_prompt` accepts `blank_lines` and `protect_code`, like `strip_comments`.
- The CLI reports a missing file with exit code 2 instead of a traceback.

## [0.1.0]

- Initial release: `strip_comments`, `load_prompt`, dialects and CLI.
