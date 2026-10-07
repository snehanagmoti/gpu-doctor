"""Turn check results into text for people or JSON for programs."""

from __future__ import annotations

import json
import shutil
import textwrap
from collections.abc import Mapping, Sequence
from typing import IO, Any

from . import __version__
from .model import CheckResult, Status, overall_status

# Bump only on an incompatible change to the JSON layout (docs/json-schema.json).
JSON_SCHEMA_VERSION = 1

EXIT_OK = 0
EXIT_WARN = 1
EXIT_FAIL = 2
EXIT_TOOL_ERROR = 3

_ANSI = {Status.PASS: "32", Status.WARN: "33", Status.FAIL: "31", Status.SKIP: "2"}
_BOLD = "1"


def exit_code(results: Sequence[CheckResult]) -> int:
    """0 all good, 1 warnings, 2 failures, 3 gpu-doctor itself hit a bug."""
    if any(r.internal_error for r in results):
        return EXIT_TOOL_ERROR
    return overall_status(list(results)).severity


def use_colour(mode: str, stream: IO[str], env: Mapping[str, str]) -> bool:
    """Colour only for a real terminal, and never when NO_COLOR is set (no-color.org)."""
    if mode == "always":
        return True
    if mode == "never" or env.get("NO_COLOR"):
        return False
    return stream.isatty() and env.get("TERM") != "dumb"


class _Style:
    def __init__(self, enabled: bool) -> None:
        self.enabled = enabled

    def __call__(self, code: str, text: str) -> str:
        return f"\033[{code}m{text}\033[0m" if self.enabled else text


def render_text(
    results: Sequence[CheckResult],
    titles: Mapping[str, str],
    *,
    verbose: bool = False,
    colour: bool = False,
    width: int | None = None,
) -> str:
    style = _Style(colour)
    width = width or min(shutil.get_terminal_size((100, 24)).columns, 100)
    title_width = max((len(titles.get(r.check_id, r.check_id)) for r in results), default=10)
    indent = " " * 6
    wrap = textwrap.TextWrapper(width=width, initial_indent=indent, subsequent_indent=indent)

    lines = [
        style(_BOLD, f"gpu-doctor {__version__}") + ": read-only NVIDIA driver diagnostics",
        "",
    ]
    for r in results:
        label = style(_ANSI[r.status], f"{r.status.name:<4}")
        title = titles.get(r.check_id, r.check_id)
        lines.append(f"{label}  {title:<{title_width}}  {r.summary}")
        show_details = verbose or r.status in (Status.WARN, Status.FAIL) or r.internal_error
        if show_details and r.explanation:
            lines.extend(wrap.wrap(r.explanation))
        if r.fixes and r.status is not Status.PASS:
            lines.append(indent + style(_BOLD, "Suggested commands (review before running):"))
            lines.extend(f"{indent}  $ {fix}" for fix in r.fixes)
        if verbose:
            lines.append(f"{indent}id: {r.check_id}")
            lines.extend(
                style(_ANSI[Status.SKIP], f"{indent}· {e.source}: {e.value}") for e in r.evidence
            )
        if show_details and (r.explanation or r.fixes or verbose):
            lines.append("")

    counts = {s: sum(1 for r in results if r.status is s) for s in Status}
    if lines[-1]:
        lines.append("")
    lines.append(
        f"{counts[Status.PASS]} passed, {counts[Status.WARN]} warnings, "
        f"{counts[Status.FAIL]} failed, {counts[Status.SKIP]} skipped. "
        "Nothing on this system was changed."
    )
    return "\n".join(line.rstrip() for line in lines) + "\n"


def to_json_document(results: Sequence[CheckResult], titles: Mapping[str, str]) -> dict[str, Any]:
    checks = []
    for r in results:
        item = r.to_dict()
        item["title"] = titles.get(r.check_id, r.check_id)
        checks.append(item)
    return {
        "schema_version": JSON_SCHEMA_VERSION,
        "tool": {"name": "gpu-doctor", "version": __version__},
        "overall_status": overall_status(list(results)).value,
        "exit_code": exit_code(results),
        "checks": checks,
    }


def render_json(results: Sequence[CheckResult], titles: Mapping[str, str]) -> str:
    return json.dumps(to_json_document(results, titles), indent=2) + "\n"
