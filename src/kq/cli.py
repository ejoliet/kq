"""argparse entry point, subcommand dispatch, exit codes."""

from __future__ import annotations

import argparse
import sys

from . import __version__

EXIT_CODES = {
    "E_USAGE": 2,
    "E_LOCKED": 3,
    "E_SQL_REJECTED": 4,
    "E_SQL": 4,
    "E_UNKNOWN_HANDLE": 5,
    "E_STORE": 6,
    "E_INTERNAL": 70,
}


class KqError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


def warn(message: str) -> None:
    print(f"kq: {message}", file=sys.stderr)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="kq", add_help=True)
    p.add_argument("--version", action="version", version=__version__)
    p.add_argument("--session", default=None, help="session id (default: derived from cwd)")
    sub = p.add_subparsers(dest="cmd", required=True)

    run = sub.add_parser("run", help="run a command and capture large stdout")
    run.add_argument("--as", dest="as_name", default=None, help="store under this handle")
    run.add_argument("--session", default=None)

    index = sub.add_parser("index", help="list current artifacts")
    index.add_argument("--all", action="store_true")
    index.add_argument("--session", default=None)

    return p


def _split_command(argv: list[str]) -> tuple[list[str], list[str]]:
    if "--" in argv:
        i = argv.index("--")
        return argv[:i], argv[i + 1 :]
    return argv, []


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    argv, command = _split_command(argv)
    args = build_parser().parse_args(argv)

    try:
        if args.cmd == "run":
            from .capture import cmd_run

            if not command:
                raise KqError("E_USAGE", "kq run needs a command after --")
            return cmd_run(args.session, args.as_name, command)
        if args.cmd == "index":
            from .index import cmd_index

            return cmd_index(args.session, args.all)
        raise KqError("E_USAGE", f"unknown command {args.cmd}")
    except KqError as e:
        warn(f"{e.code}: {e.message}")
        return EXIT_CODES.get(e.code, 70)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
