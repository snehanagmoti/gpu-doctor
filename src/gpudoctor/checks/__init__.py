"""The registry of checks.

An explicit, ordered tuple rather than decorator-based auto-discovery: the
order is the order of the report, dependencies always come before the checks
that need them, and anyone can see the full list in one place.
"""

from __future__ import annotations

from ..runner import Check
from . import gpu_present, system_info

ALL_CHECKS: tuple[Check, ...] = (
    system_info.CHECK,
    gpu_present.CHECK,
)

__all__ = ["ALL_CHECKS"]
