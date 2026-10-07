"""The registry of checks.

An explicit, ordered tuple rather than decorator-based auto-discovery: the
order is the order of the report, dependencies always come before the checks
that need them, and anyone can see the full list in one place.
"""

from __future__ import annotations

from ..runner import Check
from . import (
    driver_package,
    gpu_present,
    kernel_headers,
    kernel_module,
    module_build,
    nouveau,
    secure_boot,
    system_info,
    version_mismatch,
)

ALL_CHECKS: tuple[Check, ...] = (
    system_info.CHECK,
    gpu_present.CHECK,
    driver_package.CHECK,
    kernel_module.CHECK,
    module_build.CHECK,
    kernel_headers.CHECK,
    nouveau.CHECK,
    secure_boot.CHECK,
    version_mismatch.CHECK,
)

__all__ = ["ALL_CHECKS"]
