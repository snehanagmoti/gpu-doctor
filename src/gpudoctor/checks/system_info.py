"""Check 1: which OS, kernel and architecture are we looking at?

Informational: it only warns when the OS is not Ubuntu (or an Ubuntu
derivative), because every fix this tool suggests assumes Ubuntu packages.
"""

from __future__ import annotations

from ..model import CheckResult, Evidence, Status
from ..probe import SystemProbe
from ..runner import Check
from ..system import container_type, kernel_release, os_release

ID = "system_info"


def run(probe: SystemProbe) -> CheckResult:
    osr = os_release(probe)
    kernel = kernel_release(probe) or "unknown"
    arch = probe.machine()
    container = container_type(probe)
    pretty = osr.get("PRETTY_NAME") or osr.get("NAME") or "Unknown Linux"

    facts = {
        "os_id": osr.get("ID", ""),
        "os_version": osr.get("VERSION_ID", ""),
        "os_codename": osr.get("VERSION_CODENAME", ""),
        "kernel": kernel,
        "arch": arch,
        "container": container or "",
    }
    evidence = (
        Evidence("/etc/os-release", f"ID={facts['os_id']} VERSION_ID={facts['os_version']}"),
        Evidence("/proc/sys/kernel/osrelease", kernel),
        Evidence("uname -m", arch),
    )
    summary = f"{pretty}, kernel {kernel}, {arch}"
    if container:
        summary += f" (inside a {container} container)"

    is_ubuntu = facts["os_id"] == "ubuntu" or "ubuntu" in osr.get("ID_LIKE", "").split()
    if not is_ubuntu:
        return CheckResult(
            ID,
            Status.WARN,
            summary,
            explanation=(
                "gpu-doctor is written for Ubuntu. The checks still run, but the "
                "suggested commands (ubuntu-drivers, apt package names) may not "
                "apply to this distribution."
            ),
            evidence=evidence,
            facts=facts,
        )
    explanation = ""
    if container:
        explanation = (
            "Inside a container the kernel and its modules belong to the host, "
            "so module checks describe the host, while package checks describe "
            "the container."
        )
    return CheckResult(
        ID, Status.PASS, summary, explanation=explanation, evidence=evidence, facts=facts
    )


CHECK = Check(id=ID, title="System information", func=run)
