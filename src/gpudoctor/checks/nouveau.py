"""Check 7: is the open-source nouveau driver holding the GPU?

Only one driver can bind to a device. If nouveau loads first, nvidia.ko
cannot take the GPU. The NVIDIA packages ship a modprobe blacklist, but
nouveau can also be loaded from the initramfs (the early-boot image), which
only picks up a new blacklist after ``update-initramfs -u``.
"""

from __future__ import annotations

import re

from ..model import CheckResult, Evidence, Status
from ..probe import SystemProbe
from ..runner import Check
from ..system import (
    installed_packages_or_none,
    loaded_modules,
    nvidia_driver_packages,
    nvidia_kernel_version,
)

ID = "nouveau"

MODPROBE_DIRS = ("/etc/modprobe.d", "/run/modprobe.d", "/lib/modprobe.d", "/usr/lib/modprobe.d")
_BLACKLIST_LINE = re.compile(r"^\s*(blacklist\s+nouveau|alias\s+nouveau\s+off)\s*$", re.MULTILINE)
_CMDLINE_BLOCK = re.compile(
    r"(?:^|\s)(modprobe\.blacklist=\S*nouveau\S*|rd\.driver\.blacklist=\S*nouveau\S*|nouveau\.modeset=0)(?=\s|$)"
)

BLACKLIST_FIX = (
    "printf 'blacklist nouveau\\noptions nouveau modeset=0\\n' "
    "| sudo tee /etc/modprobe.d/blacklist-nouveau.conf"
)


def blacklist_sources(probe: SystemProbe) -> list[str]:
    """Where nouveau is blocked: modprobe.d files and/or the kernel command line."""
    sources = []
    for directory in MODPROBE_DIRS:
        try:
            paths = probe.glob(f"{directory}/*.conf")
        except PermissionError:  # some directories are hidden from a snap
            continue
        for path in paths:
            try:
                text = probe.read_text(path) or ""
            except PermissionError:
                continue
            if _BLACKLIST_LINE.search(text):
                sources.append(path)
    cmdline = probe.read_text("/proc/cmdline") or ""
    match = _CMDLINE_BLOCK.search(cmdline)
    if match:
        sources.append(f"/proc/cmdline ({match.group(1)})")
    return sources


def run(probe: SystemProbe) -> CheckResult:
    modules = loaded_modules(probe)
    sources = blacklist_sources(probe)
    packages = installed_packages_or_none(probe)
    # Unknown (inside a snap) counts as installed: nouveau loaded is then worth a FAIL.
    nvidia_installed = (
        packages is None
        or bool(nvidia_driver_packages(packages))
        or bool(nvidia_kernel_version(probe))
    )
    evidence = (
        Evidence(
            "/proc/modules", "nouveau loaded" if "nouveau" in modules else "nouveau not loaded"
        ),
        Evidence("nouveau blacklist", ", ".join(sources) or "none found"),
    )

    if "nouveau" not in modules:
        how = f" (blocked by {sources[0]})" if sources else ""
        return CheckResult(ID, Status.PASS, f"nouveau is not loaded{how}", evidence=evidence)

    if not nvidia_installed:
        return CheckResult(
            ID,
            Status.PASS,
            "The open-source nouveau driver is in use (no NVIDIA driver is installed)",
            explanation="This is fine for a desktop, but nouveau does not support CUDA.",
            evidence=evidence,
        )

    if sources:
        return CheckResult(
            ID,
            Status.FAIL,
            "nouveau is loaded even though it is blacklisted",
            explanation=(
                f"nouveau is blacklisted in {', '.join(sources)}, but it still loaded. "
                "The initramfs was probably built before the blacklist existed and "
                "loads nouveau during early boot. Rebuild it and reboot."
            ),
            fixes=("sudo update-initramfs -u", "sudo reboot"),
            evidence=evidence,
        )
    return CheckResult(
        ID,
        Status.FAIL,
        "nouveau is loaded and is holding the GPU, so the NVIDIA driver cannot",
        explanation=(
            "The NVIDIA driver is installed, but the open-source nouveau driver bound "
            "to the GPU first and no blacklist stops it. Blacklist nouveau, rebuild "
            "the initramfs so early boot also respects it, and reboot."
        ),
        fixes=(BLACKLIST_FIX, "sudo update-initramfs -u", "sudo reboot"),
        evidence=evidence,
    )


CHECK = Check(id=ID, title="No nouveau conflict", func=run, requires=("gpu_present",))
