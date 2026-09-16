"""``prompt-comments`` command-line interface."""

from __future__ import annotations

import argparse
import sys
from typing import Optional, Sequence

from .core import strip_comments
from .dialects import list_dialects
from .loader import detect_dialect


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="prompt-comments",
        description="Strip comments from a prompt file (or stdin) and print the result.",
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
        help="Drop lines that become empty after their comment is removed.",
    )
    parser.add_argument(
        "--list-dialects",
        action="store_true",
        help="List available dialect names and exit.",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.list_dialects:
        for name in list_dialects():
            print(name)
        return 0

    if args.path:
        with open(args.path, "r", encoding="utf-8") as f:
            text = f.read()
        dialect = args.dialect or detect_dialect(args.path)
    else:
        text = sys.stdin.read()
        dialect = args.dialect or "default"

    sys.stdout.write(strip_comments(text, dialect=dialect, strip_blank_lines=args.strip_blank_lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
