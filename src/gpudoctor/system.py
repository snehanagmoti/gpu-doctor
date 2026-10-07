"""Small, pure helpers for facts that several checks need.

Each helper takes a ``SystemProbe`` and returns plain data. Parsing functions
take strings so they can be unit-tested without any filesystem at all.
"""

from __future__ import annotations

import re
import weakref
from collections.abc import Iterable
from dataclasses import dataclass

from .probe import SystemProbe

NVIDIA_VENDOR_ID = "10de"

# ---------------------------------------------------------------------------
# Versions


def version_tuple(version: str) -> tuple[int, ...]:
    """``"550.54.14"`` -> ``(550, 54, 14)``. Non-numeric parts are ignored."""
    return tuple(int(part) for part in re.findall(r"\d+", version))


def upstream_version(debian_version: str) -> str:
    """Strip the epoch and Debian revision: ``1:550.120-0ubuntu0.24.04.1`` -> ``550.120``."""
    version = debian_version.split(":", 1)[-1]
    if "-" in version:
        version = version.rsplit("-", 1)[0]
    return version


# ---------------------------------------------------------------------------
# OS and kernel


def parse_os_release(text: str) -> dict[str, str]:
    """Parse the KEY=value format of os-release(5), removing shell quoting."""
    data: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        data[key.strip()] = value
    return data


def os_release(probe: SystemProbe) -> dict[str, str]:
    for path in ("/etc/os-release", "/usr/lib/os-release"):
        text = probe.read_text(path)
        if text is not None:
            return parse_os_release(text)
    return {}


def kernel_release(probe: SystemProbe) -> str | None:
    """The running kernel, same as ``uname -r`` (e.g. ``6.8.0-45-generic``)."""
    text = probe.read_text("/proc/sys/kernel/osrelease")
    return text.strip() if text and text.strip() else None


def kernel_flavour(release: str) -> str | None:
    """``6.8.0-45-generic`` -> ``generic``; ``6.8.0-1015-aws`` -> ``aws``."""
    match = re.match(r"^\d+\.\d+\.\d+-\d+-(.+)$", release)
    return match.group(1) if match else None


def multiarch_triplet(machine: str) -> str:
    """Debian multiarch library directory name for a ``uname -m`` value."""
    return {
        "x86_64": "x86_64-linux-gnu",
        "aarch64": "aarch64-linux-gnu",
        "ppc64le": "powerpc64le-linux-gnu",
        "i686": "i386-linux-gnu",
    }.get(machine, f"{machine}-linux-gnu")


def container_type(probe: SystemProbe) -> str | None:
    """Name of the container technology we run inside, or ``None`` on bare metal/VM.

    Inside a container ``/proc/modules`` shows the *host* kernel, but
    ``/var/lib/dpkg/status`` is the container's own, so some checks behave
    differently.
    """
    # systemd (and LXD/LXC images) write the container type here.
    systemd = probe.read_text("/run/systemd/container")
    if systemd and systemd.strip():
        return systemd.strip()
    if probe.exists("/.dockerenv"):
        return "docker"
    if probe.exists("/run/.containerenv"):
        return "podman"
    env = probe.getenv("container")
    return env or None


# ---------------------------------------------------------------------------
# Kernel modules


def loaded_modules(probe: SystemProbe) -> set[str]:
    """Names of loaded modules. Exact names, so ``nvidia`` != ``nvidia_uvm``."""
    text = probe.read_text("/proc/modules") or ""
    return {line.split()[0] for line in text.splitlines() if line.strip()}


_NVRM_RE = re.compile(r"Kernel Module(?:\s+for\s+\S+)?\s+(\d+(?:\.\d+)+)")


def parse_nvrm_version(text: str) -> str | None:
    """Version from ``/proc/driver/nvidia/version``.

    Proprietary module:
      NVRM version: NVIDIA UNIX x86_64 Kernel Module  550.120  Fri Sep ...
    Open kernel module:
      NVRM version: NVIDIA UNIX Open Kernel Module for x86_64  550.120  Release Build ...
    """
    match = _NVRM_RE.search(text)
    return match.group(1) if match else None


def nvidia_kernel_version(probe: SystemProbe) -> str | None:
    text = probe.read_text("/proc/driver/nvidia/version")
    return parse_nvrm_version(text) if text else None


# ---------------------------------------------------------------------------
# dpkg


@dataclass(frozen=True)
class Package:
    name: str
    version: str
    architecture: str


def parse_dpkg_status(text: str) -> dict[str, Package]:
    """Installed packages from ``/var/lib/dpkg/status`` (RFC 822-style stanzas).

    Reading the file directly instead of calling ``dpkg-query`` means this
    also works inside a strictly confined snap, where host binaries are not
    available.
    """
    packages: dict[str, Package] = {}
    for stanza in re.split(r"\n\s*\n", text):
        fields: dict[str, str] = {}
        for line in stanza.splitlines():
            if not line or line[0] in " \t":  # continuation lines (descriptions)
                continue
            key, sep, value = line.partition(":")
            if sep:
                fields[key] = value.strip()
        name = fields.get("Package")
        # "install ok installed" is the only fully installed state; packages
        # that were removed but not purged show "deinstall ok config-files".
        if not name or not fields.get("Status", "").endswith(" installed"):
            continue
        if name not in packages:  # multi-arch: keep the first (usually native)
            packages[name] = Package(
                name, fields.get("Version", ""), fields.get("Architecture", "")
            )
    return packages


_package_cache: weakref.WeakKeyDictionary[SystemProbe, dict[str, Package]] = (
    weakref.WeakKeyDictionary()
)


def installed_packages(probe: SystemProbe) -> dict[str, Package]:
    """Installed packages, parsed once per probe (the file can be several MB)."""
    if probe not in _package_cache:
        text = probe.read_text("/var/lib/dpkg/status")
        _package_cache[probe] = parse_dpkg_status(text) if text else {}
    return _package_cache[probe]


def has_dpkg_database(probe: SystemProbe) -> bool:
    return probe.exists("/var/lib/dpkg/status")


@dataclass(frozen=True)
class DriverPackage:
    package: Package
    branch: str  # "550"
    variant: str  # "", "open", "server", "server-open"


_DRIVER_RE = re.compile(
    r"^nvidia-(?:driver|headless(?:-no-dkms)?)-(\d+)(?:-(server-open|server|open))?$"
)


def nvidia_driver_packages(packages: dict[str, Package]) -> list[DriverPackage]:
    """Installed NVIDIA driver metapackages (``nvidia-driver-550-open`` and friends)."""
    found = []
    for name in sorted(packages):
        match = _DRIVER_RE.match(name)
        if match:
            found.append(DriverPackage(packages[name], match.group(1), match.group(2) or ""))
    return found


def driver_branches(packages: dict[str, Package]) -> list[str]:
    """Every NVIDIA branch with installed userspace libraries or driver packages.

    More than one branch at once (say 535 and 550) is a classic broken state
    left behind by mixing apt, the CUDA repository and PPAs.
    """
    branches = {d.branch for d in nvidia_driver_packages(packages)}
    for name in packages:
        match = re.match(r"^libnvidia-compute-(\d+)(?:-server)?$", name)
        if match:
            branches.add(match.group(1))
    return sorted(branches, key=int)


def prebuilt_module_packages(packages: dict[str, Package], kernel: str) -> list[Package]:
    """Canonical's prebuilt, signed NVIDIA modules for ``kernel``.

    ``ubuntu-drivers install`` prefers these (``linux-modules-nvidia-550-6.8.0-45-generic``)
    over DKMS: they are built and signed by Canonical, so they work with
    Secure Boot and need no compiler or headers on the machine.
    """
    pattern = re.compile(
        r"^linux-modules-nvidia-\d+(?:-server)?(?:-open)?-" + re.escape(kernel) + "$"
    )
    return [packages[n] for n in sorted(packages) if pattern.match(n)]


# ---------------------------------------------------------------------------
# DKMS


@dataclass(frozen=True)
class DkmsModule:
    name: str  # "nvidia"
    version: str  # "550.120"
    built_for: tuple[str, ...]  # kernel releases with a build directory


def dkms_nvidia_modules(probe: SystemProbe) -> list[DkmsModule]:
    """NVIDIA modules registered with DKMS, and which kernels they were built for.

    Layout (DKMS 2.x on jammy and 3.x on noble agree on this part):
      /var/lib/dkms/<module>/<module-version>/<kernel>/<arch>/module/
      /var/lib/dkms/<module>/<module-version>/source -> /usr/src/<module>-<version>
    """
    modules = []
    for name in probe.list_dir("/var/lib/dkms"):
        if not name.startswith("nvidia"):
            continue
        for version in probe.list_dir(f"/var/lib/dkms/{name}"):
            base = f"/var/lib/dkms/{name}/{version}"
            # Skip DKMS 3's "kernel-<kver>-<arch>" symlinks and stray files.
            if version.startswith("kernel-") or not probe.is_dir(base):
                continue
            kernels = tuple(
                entry
                for entry in probe.list_dir(base)
                if entry not in ("source", "build") and probe.is_dir(f"{base}/{entry}")
            )
            modules.append(DkmsModule(name, version, kernels))
    return modules


# ---------------------------------------------------------------------------
# PCI


@dataclass(frozen=True)
class PciDevice:
    address: str  # "0000:01:00.0"
    vendor: str  # "10de"
    device: str  # "2684"
    pci_class: str  # "030000"
    name: str = ""

    @property
    def is_display(self) -> bool:
        # Base class 0x03 = display controller: 0x0300 VGA, 0x0302 3D controller
        # (laptops' dGPUs and datacenter cards), 0x0380 other display.
        return self.pci_class.startswith("03")

    @property
    def is_nvidia(self) -> bool:
        return self.vendor == NVIDIA_VENDOR_ID


def _hex_id(text: str | None, width: int) -> str:
    if not text:
        return ""
    return text.strip().lower().removeprefix("0x").zfill(width)


def pci_devices(probe: SystemProbe) -> list[PciDevice]:
    """PCI devices from sysfs. No ``lspci`` needed, so it works inside a snap."""
    devices = []
    for address in probe.list_dir("/sys/bus/pci/devices"):
        base = f"/sys/bus/pci/devices/{address}"
        devices.append(
            PciDevice(
                address=address,
                vendor=_hex_id(probe.read_text(f"{base}/vendor"), 4),
                device=_hex_id(probe.read_text(f"{base}/device"), 4),
                pci_class=_hex_id(probe.read_text(f"{base}/class"), 6),
            )
        )
    return devices


_LSPCI_RE = re.compile(
    r"^(?P<addr>\S+)\s.*?\[(?P<cls>[0-9a-f]{4})\]:.*\[(?P<ven>[0-9a-f]{4}):(?P<dev>[0-9a-f]{4})\]",
    re.IGNORECASE,
)


def parse_lspci(text: str) -> list[PciDevice]:
    """Parse ``lspci -nn`` (used only when sysfs is not readable)."""
    devices = []
    for line in text.splitlines():
        match = _LSPCI_RE.match(line)
        if match:
            addr = match.group("addr")
            if addr.count(":") == 1:  # lspci omits the PCI domain by default
                addr = "0000:" + addr
            devices.append(
                PciDevice(
                    addr,
                    match.group("ven").lower(),
                    match.group("dev").lower(),
                    match.group("cls").lower() + "00",
                )
            )
    return devices


PCI_IDS_PATHS = ("/usr/share/misc/pci.ids", "/usr/share/hwdata/pci.ids")


def pci_device_names(probe: SystemProbe, wanted: Iterable[tuple[str, str]]) -> dict[str, str]:
    """Look up human names in the pci.ids database for ``(vendor, device)`` pairs.

    Returns ``{"10de:2684": "AD102 [GeForce RTX 4090]"}``. Missing database
    or unknown IDs simply give no entry.
    """
    wanted_set = {(v.lower(), d.lower()) for v, d in wanted}
    vendors = {v for v, _ in wanted_set}
    names: dict[str, str] = {}
    text = None
    for path in PCI_IDS_PATHS:
        text = probe.read_text(path)
        if text:
            break
    if not text:
        return names
    vendor: str | None = None
    for line in text.splitlines():
        if not line or line.startswith("#"):
            continue
        if not line[0].isspace():
            vendor = line[:4].lower()
            if vendor == "ffff":  # end of the vendor section (class list follows)
                break
            continue
        if vendor in vendors and line.startswith("\t") and not line.startswith("\t\t"):
            device, _, name = line.strip().partition(" ")
            if (vendor, device.lower()) in wanted_set:
                names[f"{vendor}:{device.lower()}"] = name.strip()
    return names
