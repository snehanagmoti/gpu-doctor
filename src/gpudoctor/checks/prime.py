"""Check 13 (optional): on a hybrid-graphics laptop, which GPU is selected?

Ubuntu's nvidia-prime package switches between profiles with
``prime-select nvidia|on-demand|intel``. It stores the choice in
/etc/prime-discrete ("on", "on-demand", "off"), which we read directly;
``prime-select query`` is the fallback. The "intel" profile (which also
means "integrated" on AMD machines) powers the NVIDIA GPU off, a
surprisingly common reason for "nvidia-smi says no devices".
"""

from __future__ import annotations

from ..model import CheckResult, Evidence, Status
from ..probe import SystemProbe
from ..runner import Check
from ..system import pci_devices

ID = "prime"

PRIME_FILE = "/etc/prime-discrete"
_FILE_TO_PROFILE = {"on": "nvidia", "off": "intel", "on-demand": "on-demand"}


def run(probe: SystemProbe) -> CheckResult:
    displays = [d for d in pci_devices(probe) if d.is_display]
    integrated = [d for d in displays if not d.is_nvidia]
    if not integrated or len(displays) == len(integrated):
        return CheckResult(ID, Status.SKIP, "Not a hybrid-graphics system")

    profile = None
    text = probe.read_text(PRIME_FILE)
    source = PRIME_FILE
    if text is not None:
        profile = _FILE_TO_PROFILE.get(text.strip())
    if profile is None:
        result = probe.run(["prime-select", "query"])
        if result is not None and result.returncode == 0:
            profile, source = result.stdout.strip() or None, "prime-select query"
    if profile is None:
        return CheckResult(
            ID, Status.SKIP, "Hybrid graphics detected, but the PRIME profile is unknown"
        )

    evidence = (Evidence(source, profile),)
    facts = {"prime_profile": profile}
    if profile == "intel":
        return CheckResult(
            ID,
            Status.WARN,
            "PRIME is set to the integrated GPU, so the NVIDIA GPU is powered off",
            explanation=(
                "Everything runs on the integrated GPU and CUDA cannot see the NVIDIA GPU. "
                "'on-demand' keeps the desktop on the integrated GPU but lets CUDA and "
                "selected apps use the NVIDIA GPU. Log out and back in after switching."
            ),
            fixes=("sudo prime-select on-demand",),
            evidence=evidence,
            facts=facts,
        )
    if profile == "on-demand":
        return CheckResult(
            ID,
            Status.PASS,
            "PRIME profile: on-demand (CUDA works; graphics apps use the NVIDIA GPU when asked)",
            explanation=(
                "Run a graphics app on the NVIDIA GPU with "
                "__NV_PRIME_RENDER_OFFLOAD=1 __GLX_VENDOR_LIBRARY_NAME=nvidia <app>."
            ),
            evidence=evidence,
            facts=facts,
        )
    return CheckResult(ID, Status.PASS, f"PRIME profile: {profile}", evidence=evidence, facts=facts)


CHECK = Check(id=ID, title="Hybrid graphics (PRIME)", func=run, requires=("gpu_present",))
