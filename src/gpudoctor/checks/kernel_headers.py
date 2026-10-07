"""Check 6: are kernel headers there for DKMS to build against?

Only relevant when the driver is built with DKMS; Canonical's prebuilt
modules need no headers. Two things are checked:

* headers for the *running* kernel (``/lib/modules/<k>/build``), and
* the ``linux-headers-<flavour>`` metapackage, which makes apt install
  headers for *future* kernels. Without it the next kernel upgrade arrives
  without headers, DKMS cannot build, and the driver breaks after a reboot.
  Catching this before it bites is the most useful thing this check does.
"""

from __future__ import annotations

import re

from ..model import CheckResult, Evidence, Status
from ..probe import SystemProbe
from ..runner import Check
from ..system import container_type, installed_packages, kernel_flavour, kernel_release
from .module_build import dkms_in_use

ID = "kernel_headers"


def run(probe: SystemProbe) -> CheckResult:
    if container_type(probe):
        return CheckResult(ID, Status.SKIP, "Inside a container; headers are needed on the host")
    kernel = kernel_release(probe)
    if kernel is None:
        return CheckResult(ID, Status.SKIP, "Could not read the running kernel version")
    if not dkms_in_use(probe):
        return CheckResult(
            ID, Status.SKIP, "Not needed: the driver does not use DKMS (or no driver is installed)"
        )

    build = f"/lib/modules/{kernel}/build"
    have_headers = probe.exists(build) or probe.is_dir(f"/usr/src/linux-headers-{kernel}")
    evidence = [Evidence(build, "present" if have_headers else "missing (or a dangling symlink)")]

    if not have_headers:
        return CheckResult(
            ID,
            Status.FAIL,
            f"Kernel headers for {kernel} are not installed",
            explanation=(
                "DKMS compiles the nvidia module against the headers of each kernel. "
                "Without headers for the running kernel it cannot build the module."
            ),
            fixes=("sudo apt install linux-headers-$(uname -r)", "sudo dkms autoinstall"),
            evidence=tuple(evidence),
        )

    flavour = kernel_flavour(kernel)
    if flavour:
        meta = re.compile(rf"^linux-headers-{re.escape(flavour)}(-hwe-[\d.]+(-edge)?)?$")
        metas = sorted(n for n in installed_packages(probe) if meta.match(n))
        evidence.append(
            Evidence(
                "/var/lib/dpkg/status",
                ", ".join(metas) or f"no linux-headers-{flavour} metapackage",
            )
        )
        if not metas:
            return CheckResult(
                ID,
                Status.WARN,
                f"linux-headers-{flavour} is missing, so future kernels will lack headers",
                explanation=(
                    f"Headers for {kernel} are present, but the linux-headers-{flavour} "
                    "metapackage is not installed. The next kernel upgrade will then "
                    "arrive without headers, DKMS will fail to build the nvidia module, "
                    "and the GPU will stop working after the reboot. On a HWE kernel "
                    "install linux-headers-generic-hwe-<release> instead."
                ),
                fixes=(f"sudo apt install linux-headers-{flavour}",),
                evidence=tuple(evidence),
            )
    return CheckResult(
        ID, Status.PASS, f"Kernel headers for {kernel} are installed", evidence=tuple(evidence)
    )


CHECK = Check(id=ID, title="Kernel headers installed", func=run, requires=("gpu_present",))
