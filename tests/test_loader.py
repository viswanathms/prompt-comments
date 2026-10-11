from prompt_comments import detect_dialect, load_prompt


def test_detect_dialect_from_extension():
    assert detect_dialect("prompt.j2") == "jinja"
    assert detect_dialect("prompt.md") == "markdown"
    assert detect_dialect("prompt.yaml") == "yaml"
    assert detect_dialect("prompt.unknownext") == "default"


def test_load_prompt_auto_detects_dialect(tmp_path):
    p = tmp_path / "system.md"
    p.write_text("You are a helpful assistant. <!-- internal note --> Be concise.")
    assert load_prompt(p) == "You are a helpful assistant.  Be concise."


def test_load_prompt_explicit_dialect_overrides_extension(tmp_path):
    p = tmp_path / "system.txt"
    p.write_text("role: system # not stripped by default dialect")
    assert load_prompt(p, dialect="yaml") == "role: system"


def test_load_prompt_strip_blank_lines(tmp_path):
    p = tmp_path / "prompt.j2"
    p.write_text("keep\n{# drop entire line #}\nkeep too")
    result = load_prompt(p, strip_blank_lines=True)
    assert result == "keep\nkeep too"


def test_load_prompt_blank_lines_and_protect_code(tmp_path):
    p = tmp_path / "prompt.txt"
    p.write_text("a\n\n// note\nb\n```\n// code\n```\n")
    assert load_prompt(p, blank_lines="comment") == "a\n\nb\n```\n// code\n```\n"
    assert load_prompt(p, blank_lines="comment", protect_code=False) == "a\n\nb\n```\n```\n"


def test_load_prompt_preserves_crlf(tmp_path):
    p = tmp_path / "prompt.txt"
    p.write_bytes(b"a // x\r\nb\r\n")
    assert load_prompt(p) == "a\r\nb\r\n"
