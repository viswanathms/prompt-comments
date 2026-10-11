import random

import pytest

from prompt_comments import strip_comments


def test_fenced_code_is_protected():
    text = "intro // gone\n```python\nx = 1  // keep\n{# keep #}\n```\nafter"
    assert strip_comments(text) == "intro\n```python\nx = 1  // keep\n{# keep #}\n```\nafter"


def test_tilde_fence_and_longer_closing_fence():
    text = "~~~\n// keep\n~~~~\n// gone"
    assert strip_comments(text) == "~~~\n// keep\n~~~~\n"


def test_unterminated_fence_protects_to_end():
    assert strip_comments("a // x\n```\n// keep") == "a\n```\n// keep"


def test_inline_code_is_protected():
    assert strip_comments("use `a // b` here // gone") == "use `a // b` here"


def test_protect_code_can_be_disabled():
    assert strip_comments("```\n// x\n```", protect_code=False) == "```\n\n```"


def test_crlf_is_preserved():
    assert strip_comments("x\r\n// c\r\ny\r\n") == "x\r\n\r\ny\r\n"
    assert strip_comments("x // c\r\ny", blank_lines="comment") == "x\r\ny"


def test_blank_lines_comment_mode_keeps_paragraph_breaks():
    text = "a\n\n// note\nb\n<!-- multi\nline -->\nc"
    assert strip_comments(text, blank_lines="comment") == "a\n\nb\nc"
    assert strip_comments(text, blank_lines="all") == "a\nb\nc"
    assert strip_comments(text, strip_blank_lines=True) == "a\nb\nc"


def test_blank_lines_invalid_value():
    with pytest.raises(ValueError):
        strip_comments("x // y", blank_lines="nope")


def test_unchanged_text_returns_same_object():
    text = "nothing to see https://example.com"
    assert strip_comments(text) is text


def test_trailing_whitespace_left_by_block_comment_is_trimmed():
    assert strip_comments("hello {# c #}") == "hello"


@pytest.mark.parametrize("dialect", ["default", "all", ["markdown", "python"]])
def test_deterministic_and_never_grows_on_random_input(dialect):
    # Determinism (same input -> same output) keeps provider prompt-cache prefixes
    # stable. Strict idempotence is not guaranteed: an escape (``\\#``) is consumed
    # by the first pass, and removing one comment can splice neighbouring text
    # into a new one (e.g. ``<!--{# x #}-->``).
    rng = random.Random(1234)
    pieces = ["a", " ", "\n", "//", "#", "{#", "#}", "<!--", "-->", "`", "```", "~~~", "\\", "x y", "\r\n"]
    for _ in range(300):
        text = "".join(rng.choice(pieces) for _ in range(rng.randint(0, 25)))
        out = strip_comments(text, dialect, blank_lines="comment")
        assert out == strip_comments(text, dialect, blank_lines="comment"), repr(text)
        assert len(out) <= len(text), repr(text)
