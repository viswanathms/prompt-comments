from prompt_comments.cli import main


def test_cli_reads_file_and_strips_comments(tmp_path, capsys):
    p = tmp_path / "prompt.j2"
    p.write_text("Hello {# note #}world")
    assert main([str(p)]) == 0
    assert capsys.readouterr().out == "Hello world"


def test_cli_explicit_dialect_flag(tmp_path, capsys):
    p = tmp_path / "prompt.txt"
    p.write_text("role: system # comment")
    assert main([str(p), "-d", "yaml"]) == 0
    assert capsys.readouterr().out == "role: system"


def test_cli_list_dialects(capsys):
    assert main(["--list-dialects"]) == 0
    out = capsys.readouterr().out.splitlines()
    assert "jinja" in out
    assert "default" in out


def test_cli_reads_stdin(monkeypatch, capsys):
    import io

    monkeypatch.setattr("sys.stdin", io.StringIO("Hi {# drop #}there"))
    assert main([]) == 0
    assert capsys.readouterr().out == "Hi there"
