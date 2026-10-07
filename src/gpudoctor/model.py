"""Data model shared by every check: a status, and a result object.

Results are frozen dataclasses: once a check has produced a result nothing can
mutate it, which keeps the runner, the renderers and the tests honest.
"""

from __future__ import annotations

import enum
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any


class Status(str, enum.Enum):
    """Outcome of one check.

    Subclassing ``str`` means ``json.dumps`` writes ``"pass"`` rather than an
    enum repr, so the JSON schema stays stable even if members are reordered.
    (``enum.StrEnum`` would be nicer but only exists from Python 3.11.)
    """

    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"
    SKIP = "skip"

    @property
    def severity(self) -> int:
        """How bad this outcome is, used to pick the process exit code.

        SKIP counts as 0: "we could not or did not need to look" is not a
        problem with the user's system, so a run with only PASS and SKIP
        results exits 0.
        """
        return _SEVERITY[self]


_SEVERITY = {Status.PASS: 0, Status.SKIP: 0, Status.WARN: 1, Status.FAIL: 2}


@dataclass(frozen=True)
class Evidence:
    """One piece of raw data a check looked at, shown with ``--verbose``."""

    source: str  # usually a path ("/proc/modules") or a command ("nvidia-smi ...")
    value: str  # what was found there, trimmed to something readable

    def to_dict(self) -> dict[str, str]:
        return {"source": self.source, "value": self.value}


@dataclass(frozen=True)
class CheckResult:
    """Everything one check has to say about the system."""

    check_id: str
    status: Status
    summary: str  # one line, always shown
    explanation: str = ""  # plain-language "why", shown for WARN/FAIL
    fixes: tuple[str, ...] = ()  # shell commands the user may choose to run
    evidence: tuple[Evidence, ...] = ()
    # Machine-readable facts for --json consumers (driver_version, kernel, ...).
    facts: Mapping[str, str] = field(default_factory=dict)
    # True when the check itself crashed. The runner sets this; checks never do.
    internal_error: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.check_id,
            "status": self.status.value,
            "summary": self.summary,
            "explanation": self.explanation,
            "fixes": list(self.fixes),
            "evidence": [e.to_dict() for e in self.evidence],
            "facts": dict(self.facts),
            "internal_error": self.internal_error,
        }


def overall_status(results: list[CheckResult]) -> Status:
    """The single worst status among ``results`` (PASS if there are none)."""
    worst = Status.PASS
    for result in results:
        if result.status.severity > worst.severity:
            worst = result.status
    return worst
