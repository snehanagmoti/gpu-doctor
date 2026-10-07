"""Fake machines, one per real-world situation.

``healthy()`` is a correctly working Ubuntu 24.04 desktop with an RTX 4090
using Canonical's prebuilt, signed NVIDIA modules (what ``ubuntu-drivers
install`` gives you). Every other scenario is written as a *diff* against a
healthy machine via ``Scenario.but(...)``, so it is obvious exactly which
files differ in each broken state.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path

from gpudoctor.probe import CommandResult, FakeProbe

from fsbuilder import Content, Dir, Symlink, materialise

KERNEL = "6.8.0-45-generic"
NEW_KERNEL = "6.8.0-47-generic"
SECURE_BOOT_VAR = "/sys/firmware/efi/efivars/SecureBoot-8be4df61-93ca-11d2-aa0d-e98c0322b5a7"
MOK_KEY = "/var/lib/shim-signed/mok/MOK.der"

NVIDIA_SMI_QUERY = (
    "nvidia-smi",
    "--query-gpu=name,driver_version,pci.bus_id",
    "--format=csv,noheader",
)
MOK_TEST_KEY = ("mokutil", "--test-key", MOK_KEY)

NOBLE_OS_RELEASE = """\
PRETTY_NAME="Ubuntu 24.04.1 LTS"
NAME="Ubuntu"
VERSION_ID="24.04"
VERSION="24.04.1 LTS (Noble Numbat)"
VERSION_CODENAME=noble
ID=ubuntu
ID_LIKE=debian
UBUNTU_CODENAME=noble
"""

PCI_IDS = """\
# Excerpt of the pci.ids database
10de  NVIDIA Corporation
\t2684  AD102 [GeForce RTX 4090]
\t22ba  AD102 High Definition Audio Controller
\t28e0  AD107M [GeForce RTX 4060 Max-Q / Mobile]
8086  Intel Corporation
\ta7a0  Raptor Lake-P [Iris Xe Graphics]
"""


def dpkg_status(packages: dict[str, str]) -> str:
    stanzas = [
        f"Package: {name}\nStatus: install ok installed\nPriority: optional\n"
        f"Architecture: amd64\nVersion: {version}\nDescription: {name}\n"
        for name, version in packages.items()
    ]
    return "\n".join(stanzas)


def modules_file(*names: str) -> str:
    return "".join(f"{n} 1048576 0 - Live 0x0000000000000000\n" for n in names)


def nvrm(version: str) -> str:
    return (
        f"NVRM version: NVIDIA UNIX x86_64 Kernel Module  {version}  Fri Sep 13 10:10:01 UTC 2024\n"
        "GCC version:  gcc version 13.2.0 (Ubuntu 13.2.0-23ubuntu4)\n"
    )


def pci(address: str, vendor: str, device: str, pci_class: str) -> dict[str, Content]:
    base = f"/sys/bus/pci/devices/{address}"
    return {
        f"{base}/vendor": f"0x{vendor}\n",
        f"{base}/device": f"0x{device}\n",
        f"{base}/class": f"0x{pci_class}\n",
    }


def ok(stdout: str) -> CommandResult:
    return CommandResult(0, stdout, "")


DRIVER_550 = "550.120-0ubuntu0.24.04.1"

HEALTHY_PACKAGES = {
    "nvidia-driver-550": DRIVER_550,
    "libnvidia-compute-550": DRIVER_550,
    "nvidia-utils-550": DRIVER_550,
    "nvidia-kernel-common-550": DRIVER_550,
    f"linux-modules-nvidia-550-{KERNEL}": "6.8.0-45.45+1",
    "linux-modules-nvidia-550-generic": "6.8.0-45.45+1",
    f"linux-headers-{KERNEL}": "6.8.0-45.45",
    "linux-headers-generic": "6.8.0-45.45",
    "ubuntu-drivers-common": "1:0.9.7.6ubuntu3.1",
}


@dataclass(frozen=True)
class Scenario:
    files: dict[str, Content]
    # Installed dpkg packages; written to /var/lib/dpkg/status when the probe
    # is built. ``None`` means "no dpkg database at all".
    packages: dict[str, str] | None = None
    commands: dict[tuple[str, ...], CommandResult] = field(default_factory=dict)
    env: dict[str, str] = field(default_factory=dict)
    machine: str = "x86_64"
    deny: frozenset[str] = frozenset()

    def but(
        self,
        files: dict[str, Content] | None = None,
        commands: dict[tuple[str, ...], CommandResult | None] | None = None,
        env: dict[str, str] | None = None,
        deny: set[str] | None = None,
        packages: dict[str, str | None] | None = None,
    ) -> Scenario:
        """A copy with some files/commands changed. ``None`` values delete."""
        new_files = {**self.files, **(files or {})}
        new_commands = dict(self.commands)
        for key, value in (commands or {}).items():
            if value is None:
                new_commands.pop(key, None)
            else:
                new_commands[key] = value
        new_packages = self.packages
        if packages is not None:
            new_packages = dict(self.packages or {})
            for name, version in packages.items():
                if version is None:
                    new_packages.pop(name, None)
                else:
                    new_packages[name] = version
        return replace(
            self,
            files=new_files,
            packages=new_packages,
            commands=new_commands,
            env={**self.env, **(env or {})},
            deny=self.deny | frozenset(deny or ()),
        )

    def probe(self, root: Path) -> FakeProbe:
        files = dict(self.files)
        if self.packages is not None:
            files["/var/lib/dpkg/status"] = dpkg_status(self.packages)
        materialise(root, files)
        return FakeProbe(
            root, commands=self.commands, env=self.env, machine=self.machine, deny=self.deny
        )


# ---------------------------------------------------------------------------
# Healthy baselines


def healthy() -> Scenario:
    files: dict[str, Content] = {
        "/etc/os-release": NOBLE_OS_RELEASE,
        "/proc/sys/kernel/osrelease": KERNEL + "\n",
        "/proc/sys/kernel/hostname": "sneha-desktop\n",
        "/proc/cmdline": f"BOOT_IMAGE=/boot/vmlinuz-{KERNEL} root=UUID=1234 ro quiet splash\n",
        "/proc/modules": modules_file(
            "nvidia_uvm", "nvidia_drm", "nvidia_modeset", "nvidia", "snd_hda_intel"
        ),
        "/proc/driver/nvidia/version": nvrm("550.120"),
        **pci("0000:01:00.0", "10de", "2684", "030000"),
        **pci("0000:01:00.1", "10de", "22ba", "040300"),  # the card's HDMI audio
        "/usr/share/misc/pci.ids": PCI_IDS,
        "/sys/firmware/efi/efivars": Dir(),
        SECURE_BOOT_VAR: b"\x06\x00\x00\x00\x01",
        "/sys/module/nvidia/taint": "PO\n",
        f"/usr/src/linux-headers-{KERNEL}": Dir(),
        f"/lib/modules/{KERNEL}/build": Symlink(f"/usr/src/linux-headers-{KERNEL}"),
        f"/lib/modules/{KERNEL}/kernel/nvidia-550srv/nvidia.ko": b"\x7fELF",
        "/lib/modprobe.d/nvidia-graphics-drivers.conf": (
            "blacklist nouveau\noptions nouveau modeset=0\n"
        ),
        "/usr/lib/x86_64-linux-gnu/libnvidia-ml.so.550.120": b"",
        "/usr/lib/x86_64-linux-gnu/libnvidia-ml.so.1": Symlink("libnvidia-ml.so.550.120"),
        "/usr/lib/x86_64-linux-gnu/libcuda.so.550.120": b"",
        "/usr/local/cuda-12.4/version.json": '{"cuda": {"name": "CUDA SDK", "version": "12.4.1"}}',
        "/usr/local/cuda": Symlink("/usr/local/cuda-12.4"),
    }
    commands = {NVIDIA_SMI_QUERY: ok("NVIDIA GeForce RTX 4090, 550.120, 00000000:01:00.0\n")}
    return Scenario(files=files, packages=dict(HEALTHY_PACKAGES), commands=commands)


def healthy_dkms() -> Scenario:
    """Driver built locally by DKMS, Secure Boot disabled."""
    return healthy().but(
        packages={
            f"linux-modules-nvidia-550-{KERNEL}": None,
            "linux-modules-nvidia-550-generic": None,
            "nvidia-dkms-550": DRIVER_550,
            "dkms": "3.0.11-1ubuntu13",
        },
        files={
            f"/lib/modules/{KERNEL}/kernel/nvidia-550srv/nvidia.ko": None,
            f"/var/lib/dkms/nvidia/550.120/{KERNEL}/x86_64/module/nvidia.ko.zst": b"",
            "/var/lib/dkms/nvidia/550.120/source": Dir(),
            f"/lib/modules/{KERNEL}/updates/dkms/nvidia.ko.zst": b"",
            SECURE_BOOT_VAR: b"\x06\x00\x00\x00\x00",
        },
    )


# ---------------------------------------------------------------------------
# Broken or unusual machines


def no_gpu() -> Scenario:
    """A laptop with only Intel graphics and no NVIDIA packages."""
    files: dict[str, Content] = {
        "/etc/os-release": NOBLE_OS_RELEASE,
        "/proc/sys/kernel/osrelease": KERNEL + "\n",
        "/proc/modules": modules_file("i915", "snd_hda_intel"),
        **pci("0000:00:02.0", "8086", "a7a0", "030000"),
    }
    return Scenario(files=files, packages={"linux-headers-generic": "6.8.0-45.45"})


def no_driver() -> Scenario:
    """NVIDIA GPU present, no proprietary driver installed, nouveau in use."""
    keep = {
        k: v
        for k, v in HEALTHY_PACKAGES.items()
        if not k.startswith(("nvidia", "libnvidia", "linux-modules-nvidia"))
    }
    return replace(healthy(), packages=keep).but(
        files={
            "/proc/modules": modules_file("nouveau", "snd_hda_intel"),
            "/proc/driver/nvidia/version": None,
            "/sys/module/nvidia/taint": None,
            "/lib/modprobe.d/nvidia-graphics-drivers.conf": None,
            "/usr/lib/x86_64-linux-gnu/libnvidia-ml.so.550.120": None,
            "/usr/lib/x86_64-linux-gnu/libnvidia-ml.so.1": None,
            "/usr/lib/x86_64-linux-gnu/libcuda.so.550.120": None,
            f"/lib/modules/{KERNEL}/kernel/nvidia-550srv/nvidia.ko": None,
            "/usr/local/cuda-12.4/version.json": None,
            "/usr/local/cuda": None,
        },
        commands={NVIDIA_SMI_QUERY: None},
    )


def nouveau_loaded() -> Scenario:
    """Driver installed but nouveau grabbed the GPU (no blacklist, initramfs not rebuilt)."""
    return healthy().but(
        files={
            "/proc/modules": modules_file("nouveau", "snd_hda_intel"),
            "/proc/driver/nvidia/version": None,
            "/sys/module/nvidia/taint": None,
            "/lib/modprobe.d/nvidia-graphics-drivers.conf": None,
        },
        commands={
            NVIDIA_SMI_QUERY: CommandResult(
                9,
                "",
                "NVIDIA-SMI has failed because it couldn't communicate with the NVIDIA "
                "driver. Make sure that the latest NVIDIA driver is installed and running.\n",
            )
        },
    )


def dkms_missing_after_kernel_upgrade() -> Scenario:
    """Rebooted into 6.8.0-47 but DKMS only built for 6.8.0-45 (headers missing)."""
    base = healthy_dkms()
    return base.but(
        files={
            "/proc/sys/kernel/osrelease": NEW_KERNEL + "\n",
            "/proc/modules": modules_file("snd_hda_intel"),
            "/proc/driver/nvidia/version": None,
            "/sys/module/nvidia/taint": None,
            f"/lib/modules/{NEW_KERNEL}/kernel": Dir(),
            f"/lib/modules/{NEW_KERNEL}/build": Symlink(f"/usr/src/linux-headers-{NEW_KERNEL}"),
        },
        packages={"linux-headers-generic": None},
        commands={NVIDIA_SMI_QUERY: nouveau_loaded().commands[NVIDIA_SMI_QUERY]},
    )


def secure_boot_unsigned() -> Scenario:
    """DKMS module built and installed, Secure Boot on, MOK key never enrolled."""
    return healthy_dkms().but(
        files={
            SECURE_BOOT_VAR: b"\x06\x00\x00\x00\x01",
            MOK_KEY: b"0\x82",
            "/proc/modules": modules_file("snd_hda_intel"),
            "/proc/driver/nvidia/version": None,
            "/sys/module/nvidia/taint": None,
        },
        commands={
            MOK_TEST_KEY: CommandResult(1, f"{MOK_KEY} is not enrolled\n", ""),
            NVIDIA_SMI_QUERY: nouveau_loaded().commands[NVIDIA_SMI_QUERY],
        },
    )


def version_mismatch() -> Scenario:
    """apt upgraded the libraries to 550.120 but the old 550.90.07 module is still loaded."""
    return healthy().but(
        files={"/proc/driver/nvidia/version": nvrm("550.90.07")},
        commands={
            NVIDIA_SMI_QUERY: CommandResult(
                18,
                "Failed to initialize NVML: Driver/library version mismatch\n"
                "NVML library version: 550.120\n",
                "",
            )
        },
    )


def run_installer() -> Scenario:
    """Driver installed with NVIDIA's .run installer: works, but dpkg knows nothing about it."""
    keep = {k: v for k, v in HEALTHY_PACKAGES.items() if "nvidia" not in k}
    return replace(healthy(), packages=keep).but(
        files={
            f"/lib/modules/{KERNEL}/kernel/nvidia-550srv/nvidia.ko": None,
            f"/lib/modules/{KERNEL}/kernel/drivers/video/nvidia.ko": b"",
        }
    )


def in_docker() -> Scenario:
    """gpu-doctor running inside a Docker container on a healthy host."""
    keep = {k: v for k, v in HEALTHY_PACKAGES.items() if "nvidia" not in k}
    return replace(healthy(), packages=keep).but(
        files={
            "/.dockerenv": "",
            "/sys/firmware/efi/efivars": None,
            SECURE_BOOT_VAR: None,
        }
    )


def prebuilt_missing_for_new_kernel() -> Scenario:
    """Booted a new kernel; the prebuilt module package exists only for the old one."""
    return healthy().but(
        files={
            "/proc/sys/kernel/osrelease": NEW_KERNEL + "\n",
            "/proc/modules": modules_file("snd_hda_intel"),
            "/proc/driver/nvidia/version": None,
            "/sys/module/nvidia/taint": None,
        },
        commands={NVIDIA_SMI_QUERY: nouveau_loaded().commands[NVIDIA_SMI_QUERY]},
    )


def multiple_branches() -> Scenario:
    """535 leftovers next to the active 550 driver."""
    return healthy().but(
        packages={
            "libnvidia-compute-535": "535.183.01-0ubuntu0.24.04.1",
            "nvidia-utils-535": "535.183.01-0ubuntu0.24.04.1",
        },
        files={"/usr/lib/x86_64-linux-gnu/libnvidia-ml.so.535.183.01": b""},
    )


def old_driver_new_cuda() -> Scenario:
    """Driver 535 with CUDA 12.4 (minor-version compatibility) and CUDA 13.0 (unsupported)."""
    return healthy().but(
        packages={
            "nvidia-driver-550": None,
            "libnvidia-compute-550": None,
            "nvidia-utils-550": None,
            "nvidia-kernel-common-550": None,
            f"linux-modules-nvidia-550-{KERNEL}": None,
            "linux-modules-nvidia-550-generic": None,
            "nvidia-driver-535": "535.183.01-0ubuntu0.24.04.1",
            "libnvidia-compute-535": "535.183.01-0ubuntu0.24.04.1",
            f"linux-modules-nvidia-535-{KERNEL}": "6.8.0-45.45+1",
        },
        files={
            "/proc/driver/nvidia/version": nvrm("535.183.01"),
            "/usr/lib/x86_64-linux-gnu/libnvidia-ml.so.550.120": None,
            "/usr/lib/x86_64-linux-gnu/libnvidia-ml.so.535.183.01": b"",
            "/usr/local/cuda-13.0/version.json": '{"cuda": {"version": "13.0.1"}}',
        },
        commands={NVIDIA_SMI_QUERY: ok("NVIDIA GeForce RTX 4090, 535.183.01, 00000000:01:00.0\n")},
    )


def hybrid_integrated_only() -> Scenario:
    """Laptop with Intel + NVIDIA, PRIME profile set to the integrated GPU."""
    return healthy().but(
        files={
            **pci("0000:00:02.0", "8086", "a7a0", "030000"),
            **pci("0000:01:00.0", "10de", "28e0", "030200"),
            "/sys/bus/pci/devices/0000:01:00.1/vendor": None,
            "/sys/bus/pci/devices/0000:01:00.1/device": None,
            "/sys/bus/pci/devices/0000:01:00.1/class": None,
            "/etc/prime-discrete": "off\n",
        },
    )


def docker_without_toolkit() -> Scenario:
    return healthy().but(packages={"docker.io": "24.0.7-0ubuntu4.1"})


def legacy_bios() -> Scenario:
    return healthy().but(files={"/sys/firmware/efi/efivars": None, SECURE_BOOT_VAR: None})


def in_snap() -> Scenario:
    """gpu-doctor installed as a strictly confined snap: no host binaries."""
    return healthy().but(commands={NVIDIA_SMI_QUERY: None}, env={"SNAP": "/snap/gpu-doctor/x1"})
