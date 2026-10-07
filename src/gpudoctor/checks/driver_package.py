"""Check 3: is an NVIDIA driver installed through Ubuntu's packages?

Parses /var/lib/dpkg/status directly (no dpkg-query), see system.py.
Catches three real-world states besides "nothing installed":
* the driver was installed with NVIDIA's .run installer (dpkg knows nothing),
* libraries are installed without a driver metapackage,
* several driver branches are installed at once (leftovers from upgrades).
"""

from __future__ import annotations

import re

from ..model import CheckResult, Evidence, Status
from ..probe import SystemProbe
from ..runner import Check
from ..system import (
    container_type,
    driver_branches,
    has_dpkg_database,
    installed_packages,
    nvidia_driver_packages,
    nvidia_kernel_version,
    upstream_version,
)

ID = "driver_package"

_VARIANT_LABEL = {
    "": "proprietary kernel modules",
    "open": "open kernel modules",
    "server": "server branch, proprietary modules",
    "server-open": "server branch, open kernel modules",
}


def run(probe: SystemProbe) -> CheckResult:
    container = container_type(probe)
    if container:
        return CheckResult(
            ID,
            Status.SKIP,
            f"Inside a {container} container the driver is installed on the host, not here",
        )
    if not has_dpkg_database(probe):
        return CheckResult(
            ID, Status.SKIP, "No dpkg database found, so this is not a Debian/Ubuntu system"
        )

    packages = installed_packages(probe)
    drivers = nvidia_driver_packages(packages)
    branches = driver_branches(packages)
    running = nvidia_kernel_version(probe)
    evidence = (
        Evidence(
            "/var/lib/dpkg/status",
            ", ".join(f"{d.package.name} {d.package.version}" for d in drivers)
            or "no nvidia-driver-* or nvidia-headless-* package installed",
        ),
        Evidence("NVIDIA branches with installed packages", ", ".join(branches) or "none"),
    )

    if not drivers:
        if running:
            return CheckResult(
                ID,
                Status.WARN,
                f"NVIDIA driver {running} is running, but it was not installed with apt",
                explanation=(
                    "The driver appears to come from NVIDIA's .run installer or "
                    "another manual install. apt does not know about it, so kernel "
                    "upgrades can silently break it and installing Ubuntu's driver "
                    "packages on top causes conflicts. Ubuntu's packaged drivers "
                    "are rebuilt or re-signed automatically for every kernel."
                ),
                fixes=("sudo nvidia-uninstall", "sudo ubuntu-drivers install"),
                evidence=evidence,
                facts={"driver_source": "manual"},
            )
        if branches:
            return CheckResult(
                ID,
                Status.WARN,
                f"NVIDIA libraries ({', '.join(branches)}) are installed without a driver package",
                explanation=(
                    "Userspace libraries are present but no nvidia-driver-* metapackage "
                    "ties them to a kernel module, which usually means a half-finished "
                    "install or removal."
                ),
                fixes=("sudo ubuntu-drivers install",),
                evidence=evidence,
            )
        return CheckResult(
            ID,
            Status.FAIL,
            "No NVIDIA driver package is installed",
            explanation=(
                "The GPU is either unused or driven by the open-source nouveau driver, "
                "which does not support CUDA. 'ubuntu-drivers' picks the driver branch "
                "Ubuntu recommends for this GPU and, where available, Canonical's "
                "prebuilt and signed kernel modules, which also work with Secure Boot."
            ),
            fixes=("ubuntu-drivers list", "sudo ubuntu-drivers install"),
            evidence=evidence,
        )

    # Prefer the newest branch if, unusually, two metapackages are installed.
    main = max(drivers, key=lambda d: int(d.branch))
    facts = {
        "driver_package": main.package.name,
        "driver_branch": main.branch,
        "driver_variant": main.variant or "default",
        "driver_package_version": main.package.version,
    }
    stale = [b for b in branches if b != main.branch]
    if stale:
        stale_pkgs = sorted(
            name
            for name in packages
            if name.startswith(("nvidia-", "libnvidia-"))
            and any(re.search(rf"-{b}(-|$)", name) for b in stale)
        )
        return CheckResult(
            ID,
            Status.WARN,
            f"Packages from several driver branches are installed: {', '.join(branches)}",
            explanation=(
                f"{main.package.name} is the active driver, but packages from branch "
                f"{', '.join(stale)} are still installed. Mixed branches are a common "
                "cause of 'Driver/library version mismatch' and broken CUDA. They are "
                "usually left over from an earlier driver or from NVIDIA's CUDA repository."
            ),
            fixes=(f"sudo apt purge {' '.join(stale_pkgs)}",) if stale_pkgs else (),
            evidence=evidence,
            facts=facts,
        )
    return CheckResult(
        ID,
        Status.PASS,
        f"{main.package.name} {upstream_version(main.package.version)} "
        f"({_VARIANT_LABEL.get(main.variant, main.variant)})",
        evidence=evidence,
        facts=facts,
    )


CHECK = Check(id=ID, title="Driver package installed", func=run, requires=("gpu_present",))
