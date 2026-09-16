import pytest

from prompt_comments import strip_comments
from prompt_comments.dialects import list_dialects


def test_default_strips_jinja_block():
    assert strip_comments("Hello {# note to self #}world") == "Hello world"


def test_default_strips_html_block():
    text = "Line one\n<!-- drop this\nand this -->\nLine two"
    assert strip_comments(text) == "Line one\n\nLine two"


def test_default_strips_slash_line_comment():
    text = "Be concise. // internal note\nBe kind."
    assert strip_comments(text) == "Be concise.\nBe kind."


def test_default_preserves_url_double_slash():
    text = "See https://example.com/path for details."
    assert strip_comments(text) == text


def test_default_does_not_strip_hash_by_default():
    text = "# Heading\nBody # not stripped in default dialect"
    assert strip_comments(text) == text


def test_yaml_dialect_strips_hash_line_comment():
    text = "role: system # who is speaking"
    assert strip_comments(text, dialect="yaml") == "role: system"


def test_multiple_dialects_combined():
    text = "role: system # yaml comment\nGreet the user. // js comment"
    result = strip_comments(text, dialect=["yaml", "c"])
    assert result == "role: system\nGreet the user."


def test_escaped_marker_is_preserved_literally():
    text = r"The price is \# 3 today"
    assert strip_comments(text, dialect="yaml") == "The price is # 3 today"


def test_liquid_block_comment():
    text = "before {% comment %} secret {% endcomment %} after"
    assert strip_comments(text, dialect="liquid") == "before  after"


def test_handlebars_short_and_long_forms():
    text = "a {{! short }} b {{!-- long --}} c"
    assert strip_comments(text, dialect="handlebars") == "a  b  c"


def test_sql_dialect_line_and_block():
    text = "SELECT * FROM t -- pick everything\n/* multi\nline */ WHERE 1=1"
    assert strip_comments(text, dialect="sql") == "SELECT * FROM t\n WHERE 1=1"


def test_latex_dialect():
    # The marker only starts a comment when preceded by whitespace or line
    # start, so the literal "100%" survives while " % this is..." is dropped.
    text = r"100% done % this is a latex comment"
    assert strip_comments(text, dialect="latex") == "100% done"


def test_strip_blank_lines_option():
    text = "keep\n// only a comment\nkeep too"
    result = strip_comments(text, dialect="c", strip_blank_lines=True)
    assert result == "keep\nkeep too"


def test_unknown_dialect_raises():
    with pytest.raises(ValueError):
        strip_comments("text", dialect="not-a-real-dialect")


def test_all_dialect_is_superset_and_listed():
    assert "all" in list_dialects()
    assert "jinja" in list_dialects()
    assert "jinja2" in list_dialects()


def test_dialect_alias_jinja2_matches_jinja():
    text = "keep {# drop #} keep"
    assert strip_comments(text, dialect="jinja2") == strip_comments(text, dialect="jinja")


def test_no_dialects_selected_is_noop_for_line_only_text():
    # "markdown" dialect only defines block comments; a lone // survives.
    text = "visit https://example.com // not stripped"
    assert strip_comments(text, dialect="markdown") == text
