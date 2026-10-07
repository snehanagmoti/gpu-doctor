"""Runs checks in order, wiring up dependencies and isolating failures.

The runner is the single place that guarantees "never crash": a check that
raises becomes a SKIP result instead of a traceback. Keeping that guarantee
here, rather than in every check, means each check stays short and the
guarantee is tested once.
"""

from __future__ import annotations

import traceback
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass

from .model import CheckResult, Evidence, Status
from .probe import SystemProbe

ISSUES_URL = "https://github.com/snehanagmoti/gpu-doctor/issues"

CheckFunc = Callable[[SystemProbe], CheckResult]


@dataclass(frozen=True)
class Check:
    id: str
    title: str
    func: CheckFunc
    # Ids of checks that must PASS or WARN first. If one did not, this check
    # is skipped: there is no point asking "is the module loaded?" on a
    # machine with no NVIDIA GPU.
    requires: tuple[str, ...] = ()


class UnknownCheckError(ValueError):
    pass


def select_checks(all_checks: Sequence[Check], wanted: Iterable[str] | None) -> list[Check]:
    """The checks to run for ``--check`` ids, plus everything they depend on.

    Order follows ``all_checks`` so dependencies always run first.
    """
    if wanted is None:
        return list(all_checks)
    by_id = {c.id: c for c in all_checks}
    needed: set[str] = set()
    stack = list(wanted)
    while stack:
        check_id = stack.pop()
        if check_id not in by_id:
            raise UnknownCheckError(check_id)
        if check_id not in needed:
            needed.add(check_id)
            stack.extend(by_id[check_id].requires)
    return [c for c in all_checks if c.id in needed]


def _skip(check: Check, summary: str, **kwargs: object) -> CheckResult:
    return CheckResult(check_id=check.id, status=Status.SKIP, summary=summary, **kwargs)  # type: ignore[arg-type]


def run_one(check: Check, probe: SystemProbe) -> CheckResult:
    try:
        result = check.func(probe)
    except PermissionError as exc:
        where = f" {exc.filename}" if exc.filename else ""
        return _skip(
            check,
            f"Permission denied reading{where}",
            explanation="This check needs to read a file that only root can read.",
            fixes=("sudo gpu-doctor",),
        )
    except Exception as exc:  # the never-crash guarantee
        last_frame = traceback.format_exc().strip().splitlines()[-3:]
        return _skip(
            check,
            f"Internal error in this check: {type(exc).__name__}: {exc}",
            explanation=(
                "This is a bug in gpu-doctor, not a problem with your system. "
                f"Please report it at {ISSUES_URL} with the output of "
                "'gpu-doctor --report'."
            ),
            evidence=(Evidence("traceback", " | ".join(s.strip() for s in last_frame)),),
            internal_error=True,
        )
    if result.check_id != check.id:
        return _skip(
            check,
            f"Internal error: check returned a result for {result.check_id!r}",
            internal_error=True,
        )
    return result


def run_checks(checks: Sequence[Check], probe: SystemProbe) -> list[CheckResult]:
    results: dict[str, CheckResult] = {}
    titles = {c.id: c.title for c in checks}
    for check in checks:
        unmet = [
            dep
            for dep in check.requires
            if dep not in results or results[dep].status not in (Status.PASS, Status.WARN)
        ]
        if unmet:
            dep = unmet[0]
            results[check.id] = _skip(
                check, f"Skipped: depends on '{titles.get(dep, dep)}', which did not pass"
            )
        else:
            results[check.id] = run_one(check, probe)
    return [results[c.id] for c in checks]
