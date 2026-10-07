"""Check 5: does a module exist for the kernel that is running *right now*?

``nvidia.ko`` is built for exactly one kernel version. Ubuntu delivers it in
one of two ways:

* Prebuilt: ``linux-modules-nvidia-<branch>-<kernel>``, built and signed by
  Canonical for each kernel. ``ubuntu-drivers install`` prefers this.
* DKMS: ``nvidia-dkms-<branch>`` ships source; DKMS compiles it on this
  machine for every new kernel (from /etc/kernel/postinst.d/dkms). This
  needs the matching linux-headers package and breaks if the compile fails.

The classic failure: a kernel upgrade arrives, the module for the new kernel
is not built (missing headers, compiler error) or the per-kernel prebuilt
package is missing, and after a reboot the GPU stops working.
"""

from __future__ import annotations

import re

from ..model import CheckResult, Evidence, Status
from ..probe import SystemProbe
from ..runner import Check
from ..system import (
    container_type,
    dkms_nvidia_modules,
    installed_packages,
    kernel_release,
    nvidia_driver_packages,
    prebuilt_module_packages,
)

ID = "module_build"

_PREBUILT_ANY_KERNEL = re.compile(
    r"^(linux-modules-nvidia-\d+(?:-server)?(?:-open)?)-\d+\.\d+\.\d+-\d+-\S+$"
)


def dkms_in_use(probe: SystemProbe) -> bool:
    packages = installed_packages(probe)
    return bool(dkms_nvidia_modules(probe)) or any(
        name.startswith("nvidia-dkms-") for name in packages
    )


def installed_module_files(probe: SystemProbe, kernel: str) -> list[str]:
    """Every nvidia.ko(.zst/.xz) under /lib/modules/<kernel>/."""
    return [
        p
        for p in probe.glob(f"/lib/modules/{kernel}/**/nvidia.ko*")
        if re.search(r"/nvidia\.ko(\.zst|\.xz|\.gz)?$", p)
    ]


def run(probe: SystemProbe) -> CheckResult:
    container = container_type(probe)
    if container:
        return CheckResult(
            ID, Status.SKIP, f"Inside a {container} container; kernel modules belong to the host"
        )
    kernel = kernel_release(probe)
    if kernel is None:
        return CheckResult(ID, Status.SKIP, "Could not read the running kernel version")

    packages = installed_packages(probe)
    prebuilt = prebuilt_module_packages(packages, kernel)
    dkms = dkms_nvidia_modules(probe)
    evidence = [Evidence("/proc/sys/kernel/osrelease", kernel)]
    evidence += [Evidence("/var/lib/dpkg/status", p.name) for p in prebuilt]
    evidence += [
        Evidence(
            f"/var/lib/dkms/{m.name}/{m.version}",
            "built for: " + (", ".join(m.built_for) or "no kernel"),
        )
        for m in dkms
    ]

    if prebuilt:
        return CheckResult(
            ID,
            Status.PASS,
            f"Prebuilt, Canonical-signed module {prebuilt[0].name} matches the running kernel",
            evidence=tuple(evidence),
            facts={"module_source": "prebuilt", "kernel": kernel},
        )

    if dkms:
        built = [m for m in dkms if kernel in m.built_for]
        if built:
            module = built[0]
            files = installed_module_files(probe, kernel)
            evidence += [
                Evidence(f"/lib/modules/{kernel}", ", ".join(files) or "no nvidia.ko installed")
            ]
            if not files:
                return CheckResult(
                    ID,
                    Status.WARN,
                    f"DKMS built {module.name} {module.version} for {kernel} but did not "
                    "install it",
                    explanation="The module was compiled but never copied into /lib/modules.",
                    fixes=(f"sudo dkms install {module.name}/{module.version} -k $(uname -r)",),
                    evidence=tuple(evidence),
                    facts={"module_source": "dkms", "kernel": kernel},
                )
            return CheckResult(
                ID,
                Status.PASS,
                f"DKMS module {module.name} {module.version} is built for {kernel}",
                evidence=tuple(evidence),
                facts={"module_source": "dkms", "dkms_version": module.version, "kernel": kernel},
            )
        module = dkms[0]
        other = sorted({k for m in dkms for k in m.built_for})
        fixes = []
        if not probe.exists(f"/lib/modules/{kernel}/build"):
            fixes.append("sudo apt install linux-headers-$(uname -r)")
        fixes += ["sudo dkms autoinstall", "sudo reboot"]
        log = f"/var/lib/dkms/{module.name}/{module.version}/build/make.log"
        if probe.exists(log):
            fixes.insert(0, f"less {log}")
        return CheckResult(
            ID,
            Status.FAIL,
            f"DKMS has not built the nvidia module for the running kernel {kernel}",
            explanation=(
                f"DKMS has {module.name} {module.version} built only for: "
                f"{', '.join(other) or 'no kernel'}. This usually happens after a kernel "
                "upgrade when the matching linux-headers package was missing or the "
                "build failed. Install the headers, rebuild, and reboot."
            ),
            fixes=tuple(fixes),
            evidence=tuple(evidence),
            facts={"module_source": "dkms", "kernel": kernel},
        )

    # Prebuilt packages exist, but for other kernels only.
    prefixes = sorted({m.group(1) for n in packages if (m := _PREBUILT_ANY_KERNEL.match(n))})
    if prefixes:
        return CheckResult(
            ID,
            Status.FAIL,
            f"No prebuilt NVIDIA module package for the running kernel {kernel}",
            explanation=(
                "This system uses Canonical's prebuilt modules, but the package for "
                "the kernel you booted is not installed. The linux-modules-nvidia-*-generic "
                "metapackage normally pulls it in; it can go missing when a kernel is "
                "installed manually or the metapackage was removed."
            ),
            fixes=(f"sudo apt install {prefixes[-1]}-$(uname -r)", "sudo reboot"),
            evidence=tuple(evidence),
            facts={"module_source": "prebuilt", "kernel": kernel},
        )

    files = installed_module_files(probe, kernel)
    if files:
        return CheckResult(
            ID,
            Status.PASS,
            f"nvidia module found at {files[0]} (not managed by apt or DKMS)",
            evidence=(*evidence, Evidence(f"/lib/modules/{kernel}", ", ".join(files))),
            facts={"module_source": "manual", "kernel": kernel},
        )
    if not nvidia_driver_packages(packages):
        return CheckResult(
            ID, Status.SKIP, "No NVIDIA driver is installed, so there is no module to build"
        )
    return CheckResult(
        ID,
        Status.FAIL,
        f"No nvidia module is available for the running kernel {kernel}",
        explanation=(
            "A driver package is installed but neither a prebuilt module package nor a "
            "DKMS build exists for this kernel. Reinstalling with ubuntu-drivers "
            "selects the right module package."
        ),
        fixes=("sudo ubuntu-drivers install", "sudo reboot"),
        evidence=tuple(evidence),
    )


CHECK = Check(id=ID, title="Module built for running kernel", func=run, requires=("gpu_present",))
