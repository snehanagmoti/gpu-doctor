"""Check 2: is there an NVIDIA GPU at all?

Reads ``/sys/bus/pci/devices/*/{vendor,class,device}`` instead of running
``lspci``: sysfs is always there, needs no extra package, and is readable
from inside a strictly confined snap (with the hardware-observe interface).
``lspci -nn`` is only a fallback for when sysfs shows nothing.
"""

from __future__ import annotations

from ..model import CheckResult, Evidence, Status
from ..probe import SystemProbe
from ..runner import Check
from ..system import parse_lspci, pci_device_names, pci_devices

ID = "gpu_present"


def run(probe: SystemProbe) -> CheckResult:
    devices = pci_devices(probe)
    source = "/sys/bus/pci/devices"
    if not devices:
        lspci = probe.run(["lspci", "-nn"])
        if lspci is not None and lspci.returncode == 0:
            devices = parse_lspci(lspci.stdout)
            source = "lspci -nn"

    gpus = [d for d in devices if d.is_nvidia and d.is_display]
    names = pci_device_names(probe, [(d.vendor, d.device) for d in gpus])
    labels = [
        f"{names.get(f'{d.vendor}:{d.device}', f'device {d.vendor}:{d.device}')} ({d.address})"
        for d in gpus
    ]
    evidence = tuple(
        Evidence(
            f"{source}/{d.address}" if source.startswith("/") else source,
            f"vendor=0x{d.vendor} device=0x{d.device} class=0x{d.pci_class}",
        )
        for d in devices
        if d.is_display
    ) or (Evidence(source, f"{len(devices)} PCI devices, none of them a display controller"),)

    if gpus:
        noun = "GPU" if len(gpus) == 1 else "GPUs"
        return CheckResult(
            ID,
            Status.PASS,
            f"{len(gpus)} NVIDIA {noun}: " + "; ".join(labels),
            evidence=evidence,
            facts={
                "gpu_count": str(len(gpus)),
                "gpus": "; ".join(labels),
                "pci_ids": " ".join(f"{d.vendor}:{d.device}" for d in gpus),
            },
        )

    if not devices:
        explanation = (
            "No PCI devices are visible at all. This is normal inside some "
            "containers and sandboxes; run gpu-doctor on the host instead."
        )
    else:
        explanation = (
            "No PCI display controller from NVIDIA (vendor 0x10de) was found. "
            "On a virtual machine or cloud instance the GPU must be passed "
            "through to the guest; on a laptop, check that the firmware has "
            "not disabled the discrete GPU. The remaining NVIDIA checks are "
            "skipped."
        )
    return CheckResult(
        ID,
        Status.FAIL,
        "No NVIDIA GPU found",
        explanation=explanation,
        evidence=evidence,
        facts={"gpu_count": "0"},
    )


CHECK = Check(id=ID, title="NVIDIA GPU present", func=run)
