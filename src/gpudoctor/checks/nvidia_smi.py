"""Check 10: does nvidia-smi work?

This is the end-to-end test: if nvidia-smi can talk to the driver, the
driver stack is basically healthy. It is the only check that *needs* to run
a host binary, so inside a strictly confined snap it is skipped.
"""

from __future__ import annotations

from ..model import CheckResult, Evidence, Status
from ..probe import SystemProbe
from ..runner import Check
from ..system import driver_branches, installed_packages, running_in_snap

ID = "nvidia_smi"

QUERY = ["nvidia-smi", "--query-gpu=name,driver_version,pci.bus_id", "--format=csv,noheader"]

# Known messages and what they mean, checked in order.
_KNOWN_ERRORS = (
    ("version mismatch", "The kernel module and libraries differ; reboot.", ("sudo reboot",)),
    (
        "couldn't communicate with the nvidia driver",
        "The nvidia kernel module is not loaded; see the checks above for why.",
        (),
    ),
    (
        "no devices were found",
        "The driver is loaded but sees no usable GPU.",
        ("sudo dmesg | grep -i nvidia",),
    ),
)


def run(probe: SystemProbe) -> CheckResult:
    if running_in_snap(probe):
        return CheckResult(
            ID, Status.SKIP, "Running as a snap, which cannot execute the host's nvidia-smi"
        )
    result = probe.run(QUERY, timeout=20)
    command = " ".join(QUERY)
    if result is None:
        branches = driver_branches(installed_packages(probe))
        if branches:
            return CheckResult(
                ID,
                Status.WARN,
                "nvidia-smi is not installed",
                explanation="nvidia-smi comes from the nvidia-utils package of your driver branch.",
                fixes=(f"sudo apt install nvidia-utils-{branches[-1]}",),
            )
        return CheckResult(ID, Status.SKIP, "nvidia-smi is not installed")

    output = (result.stdout + result.stderr).strip()
    evidence = (
        Evidence(command, output.splitlines()[0] if output else f"exit status {result.returncode}"),
    )
    if result.returncode == 0:
        rows = [
            [c.strip() for c in line.split(",")]
            for line in result.stdout.splitlines()
            if line.strip()
        ]
        names = [r[0] for r in rows if r]
        driver = rows[0][1] if rows and len(rows[0]) > 1 else ""
        return CheckResult(
            ID,
            Status.PASS,
            f"nvidia-smi works: {', '.join(names) or 'no GPUs listed'}"
            + (f" (driver {driver})" if driver else ""),
            evidence=evidence,
            facts={"driver_version": driver, "gpu_names": "; ".join(names)},
        )
    if result.returncode == -1:
        return CheckResult(
            ID,
            Status.WARN,
            f"nvidia-smi did not answer: {result.stderr.strip()}",
            explanation=(
                "A hung nvidia-smi usually means the GPU or driver is in a bad state; check dmesg."
            ),
            fixes=("sudo dmesg | grep -iE 'nvidia|xid'",),
            evidence=evidence,
        )
    first_line = output.splitlines()[0] if output else f"exit status {result.returncode}"
    if len(first_line) > 80:
        first_line = first_line[:79].rstrip() + "…"
    explanation = "See the checks above for the most likely cause."
    fixes: tuple[str, ...] = ()
    for needle, text, known_fixes in _KNOWN_ERRORS:
        if needle in output.lower():
            explanation, fixes = text, known_fixes
            break
    return CheckResult(
        ID,
        Status.FAIL,
        f"nvidia-smi failed: {first_line}",
        explanation=explanation,
        fixes=fixes,
        evidence=evidence,
    )


CHECK = Check(id=ID, title="nvidia-smi works", func=run, requires=("gpu_present",))
