"""Check 9: do the loaded kernel module and the userspace libraries match?

NVML refuses to work ("Failed to initialize NVML: Driver/library version
mismatch") when they differ. It happens after ``apt upgrade`` updates the
driver: new libraries land on disk immediately, but the old kernel module
stays loaded until the next reboot.

Kernel side: /proc/driver/nvidia/version.
Userspace side: the version in the file name of libnvidia-ml.so.<version>
in the multiarch library directory, falling back to the dpkg version of
libnvidia-compute-<branch>.
"""

from __future__ import annotations

import re

from ..model import CheckResult, Evidence, Status
from ..probe import SystemProbe
from ..runner import Check
from ..system import (
    installed_packages,
    multiarch_triplet,
    nvidia_kernel_version,
    upstream_version,
    version_tuple,
)

ID = "version_mismatch"

_LIB_RE = re.compile(r"/libnvidia-ml\.so\.(\d+\.\d+(?:\.\d+)?)$")


def userspace_versions(probe: SystemProbe) -> tuple[list[str], str]:
    """Installed NVML library versions and where they were found."""
    libdir = f"/usr/lib/{multiarch_triplet(probe.machine())}"
    found = sorted(
        {m.group(1) for p in probe.glob(f"{libdir}/libnvidia-ml.so.*") if (m := _LIB_RE.search(p))},
        key=version_tuple,
    )
    if found:
        return found, f"{libdir}/libnvidia-ml.so.*"
    versions = sorted(
        {
            upstream_version(pkg.version)
            for name, pkg in installed_packages(probe).items()
            if re.match(r"^libnvidia-compute-\d+(-server)?$", name)
        },
        key=version_tuple,
    )
    return versions, "/var/lib/dpkg/status (libnvidia-compute-*)"


def run(probe: SystemProbe) -> CheckResult:
    kernel_version = nvidia_kernel_version(probe)
    if kernel_version is None:
        return CheckResult(ID, Status.SKIP, "The nvidia kernel module version is not available")
    libs, source = userspace_versions(probe)
    evidence = (
        Evidence("/proc/driver/nvidia/version", kernel_version),
        Evidence(source, ", ".join(libs) or "none found"),
    )
    if not libs:
        return CheckResult(
            ID,
            Status.SKIP,
            "Could not find the NVIDIA userspace libraries (libnvidia-ml)",
            evidence=evidence,
        )
    facts = {"kernel_module_version": kernel_version, "library_version": libs[-1]}
    if libs == [kernel_version]:
        return CheckResult(
            ID,
            Status.PASS,
            f"Kernel module and libraries are both {kernel_version}",
            evidence=evidence,
            facts=facts,
        )
    if kernel_version in libs:
        return CheckResult(
            ID,
            Status.WARN,
            f"Several NVML library versions are installed: {', '.join(libs)}",
            explanation=(
                f"The loaded module ({kernel_version}) matches one of them, but leftover "
                "libraries from another driver version can be picked up by some programs."
            ),
            evidence=evidence,
            facts=facts,
        )
    return CheckResult(
        ID,
        Status.FAIL,
        f"Kernel module is {kernel_version} but the libraries are {libs[-1]}",
        explanation=(
            "This is the classic 'Failed to initialize NVML: Driver/library version "
            "mismatch'. The driver was upgraded: the new libraries are already on disk "
            "but the old kernel module is still loaded. Rebooting loads the new module."
        ),
        fixes=("sudo reboot",),
        evidence=evidence,
        facts=facts,
    )


CHECK = Check(
    id=ID, title="Module and library versions match", func=run, requires=("kernel_module",)
)
