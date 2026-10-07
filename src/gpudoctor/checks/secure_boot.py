"""Check 8: is Secure Boot rejecting an unsigned nvidia module?

Chain of trust: firmware trusts Microsoft -> Microsoft signed shim -> shim
trusts Canonical's key *and* the Machine Owner Key (MOK) list -> GRUB and the
kernel. With Secure Boot on, the kernel is in lockdown and only loads modules
signed by a trusted key ("Key was rejected by service" otherwise).

* Canonical's prebuilt modules are signed by Canonical: they just work.
* DKMS modules are signed on this machine with a local MOK key
  (/var/lib/shim-signed/mok/MOK.der). That key only counts once it is
  *enrolled*, which needs a reboot into the blue MokManager screen. People
  miss that screen, and the module then silently never loads.

Secure Boot state is read from the EFI variable directly; the first four
bytes of an efivarfs file are attribute flags, and the fifth is the value.
"""

from __future__ import annotations

from ..model import CheckResult, Evidence, Status
from ..probe import SystemProbe
from ..runner import Check
from ..system import (
    container_type,
    installed_packages,
    kernel_release,
    loaded_modules,
    prebuilt_module_packages,
    running_in_snap,
)
from .module_build import dkms_in_use, installed_module_files

ID = "secure_boot"

EFI_GLOBAL_GUID = "8be4df61-93ca-11d2-aa0d-e98c0322b5a7"
SECURE_BOOT_VAR = f"/sys/firmware/efi/efivars/SecureBoot-{EFI_GLOBAL_GUID}"
MOK_KEY = "/var/lib/shim-signed/mok/MOK.der"


def secure_boot_enabled(probe: SystemProbe) -> bool | None:
    """True/False from efivarfs, or None if it cannot be determined."""
    data = probe.read_bytes(SECURE_BOOT_VAR)
    if data is None or len(data) < 5:
        return None
    return data[4] == 1


def mok_enrolled(probe: SystemProbe) -> bool | None:
    """Ask mokutil whether the local DKMS signing key is enrolled (None = unknown)."""
    if not probe.exists(MOK_KEY):
        return None
    result = probe.run(["mokutil", "--test-key", MOK_KEY])
    if result is None:
        return None
    output = (result.stdout + result.stderr).lower()
    if "is already enrolled" in output:
        return True
    if "is not enrolled" in output:
        return False
    return None


def run(probe: SystemProbe) -> CheckResult:
    if not probe.exists("/sys/firmware/efi"):
        container = container_type(probe)
        if container:
            return CheckResult(
                ID,
                Status.SKIP,
                f"Inside a {container} container; Secure Boot is a property of the host",
            )
        return CheckResult(
            ID, Status.SKIP, "Booted in legacy BIOS mode, so Secure Boot does not apply"
        )
    enabled = secure_boot_enabled(probe)
    evidence = [
        Evidence(SECURE_BOOT_VAR, {True: "enabled", False: "disabled", None: "unreadable"}[enabled])
    ]
    if enabled is None:
        return CheckResult(
            ID,
            Status.SKIP,
            "Could not read the Secure Boot state (efivarfs not available)",
            evidence=tuple(evidence),
        )
    facts = {"secure_boot": "enabled" if enabled else "disabled"}
    if not enabled:
        return CheckResult(
            ID,
            Status.PASS,
            "Secure Boot is disabled, so unsigned modules can load",
            evidence=tuple(evidence),
            facts=facts,
        )

    if "nvidia" in loaded_modules(probe):
        return CheckResult(
            ID,
            Status.PASS,
            "Secure Boot is enabled and the nvidia module loaded, so its signature is trusted",
            evidence=tuple(evidence),
            facts=facts,
        )
    kernel = kernel_release(probe) or ""
    if prebuilt_module_packages(installed_packages(probe), kernel):
        return CheckResult(
            ID,
            Status.PASS,
            "Secure Boot is enabled; the prebuilt modules are signed by Canonical",
            evidence=tuple(evidence),
            facts=facts,
        )
    if not dkms_in_use(probe):
        return CheckResult(
            ID, Status.PASS, "Secure Boot is enabled", evidence=tuple(evidence), facts=facts
        )

    # DKMS module, Secure Boot on, module not loaded: the classic MOK problem.
    files = installed_module_files(probe, kernel)
    if files:
        signer = probe.run(["modinfo", "-F", "signer", files[0]])
        if signer is not None:
            evidence.append(
                Evidence(f"modinfo -F signer {files[0]}", signer.stdout.strip() or "unsigned")
            )
    enrolled = mok_enrolled(probe)
    evidence.append(
        Evidence(
            f"mokutil --test-key {MOK_KEY}",
            {True: "enrolled", False: "not enrolled", None: "unknown"}[enrolled],
        )
    )
    facts["mok_enrolled"] = {True: "yes", False: "no", None: "unknown"}[enrolled]

    if enrolled:
        return CheckResult(
            ID,
            Status.WARN,
            "Secure Boot is on and the MOK key is enrolled, but the nvidia module did not load",
            explanation=(
                "The local signing key is trusted, so the module may have been signed with "
                "a different key or the load failed for another reason. Load it by hand and "
                "read the kernel log; 'Key was rejected by service' means a signing problem."
            ),
            fixes=("sudo modprobe nvidia", "sudo dmesg | grep -iE 'nvidia|key was rejected'"),
            evidence=tuple(evidence),
            facts=facts,
        )

    if probe.exists(MOK_KEY):
        fixes: tuple[str, ...] = (f"sudo mokutil --import {MOK_KEY}", "sudo reboot")
        key_note = (
            "Run the import command, choose a one-time password, reboot, and pick "
            "'Enroll MOK' in the blue MokManager screen that appears before Ubuntu starts."
        )
    else:
        fixes = (
            "sudo update-secureboot-policy --new-key",
            "sudo update-secureboot-policy --enroll-key",
            "sudo reboot",
        )
        key_note = "No local MOK signing key exists yet; create one, enrol it, and reboot."
    if enrolled is None and running_in_snap(probe):
        key_note += " (gpu-doctor runs as a snap and cannot call mokutil to confirm the key state.)"
    return CheckResult(
        ID,
        Status.FAIL,
        "Secure Boot is blocking the locally built (DKMS) nvidia module",
        explanation=(
            "With Secure Boot on, the kernel only loads modules signed by a trusted key. "
            "DKMS signs the nvidia module with this machine's MOK key, which is not "
            f"enrolled. {key_note} Alternatively, 'sudo ubuntu-drivers install' switches "
            "to Canonical-signed prebuilt modules where they exist for your driver."
        ),
        fixes=fixes,
        evidence=tuple(evidence),
        facts=facts,
    )


CHECK = Check(id=ID, title="Secure Boot and module signing", func=run, requires=("gpu_present",))
