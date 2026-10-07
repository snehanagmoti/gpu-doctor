from gpudoctor import system
from gpudoctor.probe import FakeProbe

from fsbuilder import Dir, materialise

DPKG_STATUS = """\
Package: nvidia-driver-550
Status: install ok installed
Architecture: amd64
Version: 550.120-0ubuntu0.24.04.1
Description: NVIDIA driver metapackage
 Continuation line: with a colon that must be ignored.

Package: nvidia-driver-535
Status: deinstall ok config-files
Architecture: amd64
Version: 535.183.01-0ubuntu0.24.04.1

Package: libnvidia-compute-550
Status: install ok installed
Architecture: amd64
Version: 550.120-0ubuntu0.24.04.1

Package: libnvidia-compute-550
Status: install ok installed
Architecture: i386
Version: 550.120-0ubuntu0.24.04.1

Package: nvidia-headless-no-dkms-535-server-open
Status: install ok installed
Architecture: amd64
Version: 535.183.06-0ubuntu0.24.04.1

Package: linux-modules-nvidia-550-6.8.0-45-generic
Status: install ok installed
Architecture: amd64
Version: 6.8.0-45.45+1

Package: linux-modules-nvidia-550-generic
Status: install ok installed
Architecture: amd64
Version: 6.8.0-45.45+1
"""


def test_versions():
    assert system.version_tuple("550.54.14") == (550, 54, 14)
    assert system.version_tuple("550.54.14") > system.version_tuple("550.54.2")
    assert system.upstream_version("1:550.120-0ubuntu0.24.04.1") == "550.120"
    assert system.upstream_version("550.120") == "550.120"


def test_parse_os_release():
    text = 'NAME="Ubuntu"\nVERSION_ID="24.04"\n# comment\nID=ubuntu\nPRETTY_NAME=\'X Y\'\nbad\n'
    assert system.parse_os_release(text) == {
        "NAME": "Ubuntu",
        "VERSION_ID": "24.04",
        "ID": "ubuntu",
        "PRETTY_NAME": "X Y",
    }


def test_kernel_flavour():
    assert system.kernel_flavour("6.8.0-45-generic") == "generic"
    assert system.kernel_flavour("6.8.0-1015-nvidia-lowlatency") == "nvidia-lowlatency"
    assert system.kernel_flavour("6.10.3-arch1") is None


def test_multiarch_triplet():
    assert system.multiarch_triplet("x86_64") == "x86_64-linux-gnu"
    assert system.multiarch_triplet("aarch64") == "aarch64-linux-gnu"
    assert system.multiarch_triplet("riscv64") == "riscv64-linux-gnu"


def test_parse_nvrm_version_both_flavours():
    proprietary = "NVRM version: NVIDIA UNIX x86_64 Kernel Module  550.120  Fri Sep 13 2024\n"
    open_module = "NVRM version: NVIDIA UNIX Open Kernel Module for x86_64  560.35.03  Release\n"
    assert system.parse_nvrm_version(proprietary) == "550.120"
    assert system.parse_nvrm_version(open_module) == "560.35.03"
    assert system.parse_nvrm_version("garbage") is None


def test_parse_dpkg_status():
    pkgs = system.parse_dpkg_status(DPKG_STATUS)
    assert "nvidia-driver-535" not in pkgs  # removed, config files only
    assert pkgs["libnvidia-compute-550"].architecture == "amd64"  # first arch wins
    drivers = system.nvidia_driver_packages(pkgs)
    assert [(d.package.name, d.branch, d.variant) for d in drivers] == [
        ("nvidia-driver-550", "550", ""),
        ("nvidia-headless-no-dkms-535-server-open", "535", "server-open"),
    ]
    assert system.driver_branches(pkgs) == ["535", "550"]
    prebuilt = system.prebuilt_module_packages(pkgs, "6.8.0-45-generic")
    assert [p.name for p in prebuilt] == ["linux-modules-nvidia-550-6.8.0-45-generic"]
    assert system.prebuilt_module_packages(pkgs, "6.8.0-47-generic") == []


def test_installed_packages_is_cached(tmp_path):
    materialise(tmp_path, {"/var/lib/dpkg/status": DPKG_STATUS})
    probe = FakeProbe(tmp_path)
    first = system.installed_packages(probe)
    (tmp_path / "var/lib/dpkg/status").write_text("")
    assert system.installed_packages(probe) is first
    assert system.installed_packages(FakeProbe(tmp_path)) == {}


def test_container_type(tmp_path):
    assert system.container_type(FakeProbe(tmp_path)) is None
    assert system.container_type(FakeProbe(tmp_path, env={"container": "lxc"})) == "lxc"
    materialise(tmp_path, {"/.dockerenv": ""})
    assert system.container_type(FakeProbe(tmp_path)) == "docker"
    materialise(tmp_path, {"/run/systemd/container": "lxc\n"})
    assert system.container_type(FakeProbe(tmp_path)) == "lxc"


def test_podman_container(tmp_path):
    materialise(tmp_path, {"/run/.containerenv": ""})
    assert system.container_type(FakeProbe(tmp_path)) == "podman"


def test_loaded_modules_exact_names(tmp_path):
    materialise(tmp_path, {"/proc/modules": "nvidia_uvm 1 0 - Live 0x0\nnouveau 2 1 - Live 0x0\n"})
    mods = system.loaded_modules(FakeProbe(tmp_path))
    assert mods == {"nvidia_uvm", "nouveau"}
    assert "nvidia" not in mods


def test_dkms_layout(tmp_path):
    materialise(
        tmp_path,
        {
            "/var/lib/dkms/nvidia/550.120/6.8.0-40-generic/x86_64/module": Dir(),
            "/var/lib/dkms/nvidia/550.120/source": Dir(),
            "/var/lib/dkms/nvidia/kernel-6.8.0-40-generic-x86_64": "",
            "/var/lib/dkms/virtualbox/7.0/6.8.0-40-generic": Dir(),
        },
    )
    [module] = system.dkms_nvidia_modules(FakeProbe(tmp_path))
    assert module == system.DkmsModule("nvidia", "550.120", ("6.8.0-40-generic",))


def test_parse_lspci():
    out = (
        "00:02.0 VGA compatible controller [0300]: Intel Corporation [8086:a780] (rev 04)\n"
        "01:00.0 3D controller [0302]: NVIDIA Corporation AD107M [10de:28e0] (rev a1)\n"
        "garbage line\n"
    )
    devices = system.parse_lspci(out)
    assert [(d.address, d.vendor, d.device, d.pci_class) for d in devices] == [
        ("0000:00:02.0", "8086", "a780", "030000"),
        ("0000:01:00.0", "10de", "28e0", "030200"),
    ]
    assert devices[1].is_nvidia and devices[1].is_display


def test_pci_names(tmp_path):
    materialise(
        tmp_path,
        {
            "/usr/share/hwdata/pci.ids": (
                "# comment\n10de  NVIDIA Corporation\n\t2684  AD102 [GeForce RTX 4090]\n"
                "\t\t1043 889c  subsystem line\n8086  Intel\n\ta780  UHD 770\n"
                "ffff  Illegal\nC 03  Display controller\n"
            )
        },
    )
    names = system.pci_device_names(FakeProbe(tmp_path), [("10de", "2684"), ("10de", "9999")])
    assert names == {"10de:2684": "AD102 [GeForce RTX 4090]"}
    assert system.pci_device_names(FakeProbe(tmp_path / "empty"), [("10de", "2684")]) == {}
