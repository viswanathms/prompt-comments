"""``prompt-comments`` command-line interface.

    prompt-comments [PATH] [-d DIALECT]...     strip comments from a file / stdin
    prompt-comments build [SRC ...]            CLAUDE.src.md -> CLAUDE.md
    prompt-comments proxy [start|env]          local LLM proxy that strips comments on the wire

(To clean a file literally named ``build`` or ``proxy``, pass it as ``./build``.)
"""

from __future__ import annotations

import argparse
import sys
from typing import Optional, Sequence

from .core import strip_comments
from .dialects import list_dialects
from .loader import detect_dialect

SUBCOMMANDS = ("build", "proxy")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="prompt-comments",
        description="Strip comments from a prompt file (or stdin) and print the result.",
        epilog="Subcommands: 'prompt-comments build --help' (generate CLAUDE.md / AGENTS.md from "
        "commented sources), 'prompt-comments proxy --help' (strip comments from LLM requests on the wire).",
    )
    parser.add_argument("path", nargs="?", help="Prompt file to clean. Reads stdin if omitted.")
    parser.add_argument(
        "-d",
        "--dialect",
        action="append",
        help="Comment dialect to strip (repeatable). Default: inferred from the file "
        "extension, or 'default' when reading stdin.",
    )
    parser.add_argument(
        "--strip-blank-lines",
        action="store_true",
        help="Drop every blank line (same as --blank-lines all).",
    )
    parser.add_argument(
        "--blank-lines",
        choices=["keep", "comment", "all"],
        help="'comment' drops only lines that became empty because a comment was removed.",
    )
    parser.add_argument(
        "--no-protect-code",
        action="store_true",
        help="Also strip comment markers inside fenced code blocks and `inline code`.",
    )
    parser.add_argument(
        "--list-dialects",
        action="store_true",
        help="List available dialect names and exit.",
    )
    return parser


def _subcommand_parser(name: str) -> argparse.ArgumentParser:
    from . import build, proxy

    module = {"build": build, "proxy": proxy}[name]
    parser = argparse.ArgumentParser(
        prog=f"prompt-comments {name}", description=(module.__doc__ or "").strip().split("\n\n")[0]
    )
    module.add_arguments(parser)
    parser.set_defaults(_run=module.run)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)

    if argv and argv[0] in SUBCOMMANDS:
        args = _subcommand_parser(argv[0]).parse_args(argv[1:])
        return args._run(args)

    args = build_parser().parse_args(argv)

    if args.list_dialects:
        for name in list_dialects():
            print(name)
        return 0

    if args.path:
        try:
            with open(args.path, "r", encoding="utf-8", newline="") as f:  # newline="": keep CRLF
                text = f.read()
        except OSError as exc:
            print(f"prompt-comments: {exc.strerror or exc}: {args.path}", file=sys.stderr)
            return 2
        dialect = args.dialect or detect_dialect(args.path)
    else:
        text = sys.stdin.read()
        dialect = args.dialect or "default"

    sys.stdout.write(
        strip_comments(
            text,
            dialect=dialect,
            strip_blank_lines=args.strip_blank_lines,
            blank_lines=args.blank_lines,
            protect_code=not args.no_protect_code,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
