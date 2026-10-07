"""``--report``: a block of text safe to paste into a forum post or bug report.

Redaction is deliberately conservative. It removes the machine's hostname,
the current username and home directory, GPU UUIDs, serial numbers, MAC
addresses and filesystem UUIDs. The goal is that a user can paste the output
to AskUbuntu or Launchpad without thinking about it.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence

from . import __version__
from .model import CheckResult
from .probe import SystemProbe
from .render import exit_code

REDACTED = "<redacted>"

_PATTERNS = (
    # GPU UUIDs as printed by nvidia-smi: GPU-1a2b3c4d-....
    (re.compile(r"\b(GPU|MIG)-[0-9a-fA-F]{8}(-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}\b"), r"\1-<uuid>"),
    # Any other UUID (e.g. root=UUID=... on the kernel command line).
    (re.compile(r"\b[0-9a-fA-F]{8}(-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}\b"), "<uuid>"),
    # MAC addresses.
    (re.compile(r"\b([0-9a-fA-F]{2}[:-]){5}[0-9a-fA-F]{2}\b"), "<mac>"),
    # "Serial Number : 1234567890" / "serial=ABC123".
    (re.compile(r"(?i)(serial(?:[ _-]?number)?\s*[:=]\s*)\S+"), r"\1<serial>"),
)


def redact(text: str, *, hostname: str | None, username: str | None, home: str | None) -> str:
    for pattern, replacement in _PATTERNS:
        text = pattern.sub(replacement, text)
    # Longest first, so "/home/sneha" is replaced before "sneha".
    for secret, label in sorted(
        ((home, "<home>"), (hostname, "<hostname>"), (username, "<user>")),
        key=lambda item: -len(item[0] or ""),
    ):
        # Skip empty and trivially short values ("a", "pi") that would
        # mangle unrelated words; also never redact "root".
        if secret and len(secret) >= 3 and secret not in ("root", "/root"):
            text = re.sub(rf"(?<![\w-]){re.escape(secret)}(?![\w-])", label, text)
    return text


def render_report(
    results: Sequence[CheckResult], titles: Mapping[str, str], probe: SystemProbe
) -> str:
    lines = [
        f"### gpu-doctor {__version__} report (exit status {exit_code(results)})",
        "",
        "```",
    ]
    for r in results:
        lines.append(f"[{r.status.name}] {titles.get(r.check_id, r.check_id)}: {r.summary}")
        for e in r.evidence:
            lines.append(f"    {e.source}: {e.value}")
        for fix in r.fixes:
            lines.append(f"    fix: {fix}")
    lines.append("```")
    text = "\n".join(lines) + "\n"

    hostname = (probe.read_text("/proc/sys/kernel/hostname") or "").strip() or None
    return redact(
        text,
        hostname=hostname,
        username=probe.getenv("SUDO_USER") or probe.getenv("USER"),
        home=probe.getenv("HOME"),
    )
