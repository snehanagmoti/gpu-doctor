"""Command-line interface: parse arguments, run checks, print, choose the exit code."""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence
from typing import NoReturn

from . import __version__
from .checks import ALL_CHECKS
from .probe import HostProbe
from .render import EXIT_TOOL_ERROR, exit_code, render_json, render_text, use_colour
from .runner import UnknownCheckError, run_checks, select_checks

EPILOG = """\
exit status:
  0  every check passed (or was skipped)
  1  at least one warning
  2  at least one failure
  3  gpu-doctor itself failed (bad arguments or an internal error)

gpu-doctor never changes your system. It only prints commands you may choose to run.
"""


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        # argparse exits with 2 on usage errors, which would collide with
        # "a check failed". Usage errors are tool errors: exit 3.
        self.print_usage(sys.stderr)
        self.exit(EXIT_TOOL_ERROR, f"{self.prog}: error: {message}\n")


def build_parser() -> argparse.ArgumentParser:
    parser = _Parser(
        prog="gpu-doctor",
        description=(
            "Diagnose NVIDIA GPU driver and CUDA problems on Ubuntu and explain how to fix them."
        ),
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    output = parser.add_mutually_exclusive_group()
    output.add_argument(
        "--json", action="store_true", help="print machine-readable JSON (see docs/json-output.md)"
    )
    output.add_argument(
        "--report",
        action="store_true",
        help="print a bug-report block with hostname, username and serials redacted",
    )
    output.add_argument(
        "--list-checks", action="store_true", help="list the available check ids and exit"
    )
    parser.add_argument(
        "-c",
        "--check",
        action="append",
        metavar="ID",
        help="run only this check (repeatable or comma-separated); dependencies run too",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="show evidence: which files were read and what they contained"
    )
    parser.add_argument(
        "--color",
        "--colour",
        choices=("auto", "always", "never"),
        default="auto",
        help="colourise output (default: auto, which honours NO_COLOR)",
    )
    parser.add_argument(
        "--root",
        metavar="DIR",
        default="/",
        help="inspect a system image mounted at DIR instead of / (commands are not run)",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def _requested_ids(values: Sequence[str] | None) -> list[str] | None:
    if not values:
        return None
    return [part.strip() for value in values for part in value.split(",") if part.strip()]


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    titles = {c.id: c.title for c in ALL_CHECKS}

    if args.list_checks:
        width = max(len(c.id) for c in ALL_CHECKS)
        for check in ALL_CHECKS:
            print(f"{check.id:<{width}}  {check.title}")
        return 0

    try:
        checks = select_checks(ALL_CHECKS, _requested_ids(args.check))
    except UnknownCheckError as exc:
        parser.error(f"unknown check id {exc} (see --list-checks)")

    if not os.path.isdir(args.root):
        parser.error(f"--root: {args.root} is not a directory")

    try:
        probe = HostProbe(args.root)
        results = run_checks(checks, probe)
        if args.json:
            sys.stdout.write(render_json(results, titles))
        elif args.report:
            from .report import render_report

            sys.stdout.write(render_report(results, titles, probe))
        else:
            colour = use_colour(args.color, sys.stdout, os.environ)
            sys.stdout.write(render_text(results, titles, verbose=args.verbose, colour=colour))
    except BrokenPipeError:  # e.g. `gpu-doctor | head`
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, sys.stdout.fileno())
        return 0
    except Exception as exc:  # last line of defence; checks are already isolated
        print(f"gpu-doctor: internal error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return EXIT_TOOL_ERROR
    return exit_code(results)
