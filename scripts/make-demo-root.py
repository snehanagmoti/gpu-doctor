#!/usr/bin/env python3
"""Write one of the test suite's fake machines to a directory.

    python3 scripts/make-demo-root.py --list
    python3 scripts/make-demo-root.py dkms_missing_after_kernel_upgrade /tmp/demo
    gpu-doctor --root /tmp/demo

Useful for trying gpu-doctor's output for broken setups you do not have, for
recording the README demo, and for reproducing a bug report as a scenario.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "tests"), str(ROOT / "src")]

import scenarios  # noqa: E402


def available() -> list[str]:
    return sorted(
        name
        for name in dir(scenarios)
        if callable(getattr(scenarios, name))
        and getattr(getattr(scenarios, name), "__module__", "") == "scenarios"
        and getattr(scenarios, name).__annotations__.get("return") == "Scenario"
        and name != "in_snap"  # needs a snap environment, not just files
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("scenario", nargs="?")
    parser.add_argument("directory", nargs="?", type=Path)
    parser.add_argument("--list", action="store_true", help="list the scenarios")
    args = parser.parse_args()
    if args.list or not args.scenario:
        print("\n".join(available()))
        return 0
    if args.scenario not in available() or args.directory is None:
        parser.error("give a scenario from --list and a target directory")
    if args.directory.exists() and any(args.directory.iterdir()):
        parser.error(f"{args.directory} is not empty")
    args.directory.mkdir(parents=True, exist_ok=True)
    getattr(scenarios, args.scenario)().probe(args.directory)
    print(f"Wrote the '{args.scenario}' machine to {args.directory}")
    print(f"Try: gpu-doctor --root {args.directory}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
