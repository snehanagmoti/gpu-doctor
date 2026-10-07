"""Check 4: is the nvidia kernel module loaded?

Without it nothing can use the GPU. This check only reports *whether*; the
checks after it (module_build, kernel_headers, nouveau, secure_boot) each
look for one specific reason *why not*.
"""

from __future__ import annotations

from ..model import CheckResult, Evidence, Status
from ..probe import SystemProbe
from ..runner import Check
from ..system import (
    container_type,
    driver_branches,
    installed_packages_or_none,
    loaded_modules,
    nvidia_kernel_version,
)

ID = "kernel_module"

# One driver install loads up to four modules. Only "nvidia" is essential.
NVIDIA_MODULES = ("nvidia", "nvidia_modeset", "nvidia_drm", "nvidia_uvm")


def run(probe: SystemProbe) -> CheckResult:
    modules = loaded_modules(probe)
    version = nvidia_kernel_version(probe)
    loaded = [m for m in NVIDIA_MODULES if m in modules]
    evidence = (
        Evidence("/proc/modules", ", ".join(loaded) or "no nvidia modules loaded"),
        Evidence("/proc/driver/nvidia/version", version or "missing"),
    )
    if "nvidia" in modules:
        return CheckResult(
            ID,
            Status.PASS,
            f"nvidia kernel module {version} is loaded"
            if version
            else "nvidia kernel module is loaded",
            evidence=evidence,
            facts={"kernel_module_version": version or "", "loaded_modules": " ".join(loaded)},
        )
    packages = installed_packages_or_none(probe)  # None inside a snap: assume a driver
    if not container_type(probe) and packages is not None and not driver_branches(packages):
        return CheckResult(
            ID,
            Status.SKIP,
            "No NVIDIA driver is installed, so there is no module to load",
            evidence=evidence,
        )
    return CheckResult(
        ID,
        Status.FAIL,
        "The nvidia kernel module is not loaded",
        explanation=(
            "Without the kernel module no program can use the GPU. If you have just "
            "installed or upgraded the driver, reboot first. Otherwise the checks "
            "below point at the usual causes: nouveau holding the GPU, no module "
            "built for the running kernel, or Secure Boot rejecting an unsigned module. "
            "Loading it by hand shows the kernel's exact error."
        ),
        fixes=("sudo modprobe nvidia", "sudo dmesg | grep -iE 'nvidia|nouveau'"),
        evidence=evidence,
    )


CHECK = Check(id=ID, title="Kernel module loaded", func=run, requires=("gpu_present",))
