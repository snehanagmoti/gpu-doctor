"""system_info and gpu_present."""

from gpudoctor.checks import gpu_present, system_info
from gpudoctor.model import Status
from gpudoctor.probe import CommandResult

from scenarios import healthy, no_gpu, pci


def test_system_info_healthy(tmp_path):
    result = system_info.run(healthy().probe(tmp_path))
    assert result.status is Status.PASS
    assert result.summary == "Ubuntu 24.04.1 LTS, kernel 6.8.0-45-generic, x86_64"
    assert result.facts["os_codename"] == "noble"


def test_system_info_not_ubuntu(tmp_path):
    scenario = healthy().but(files={"/etc/os-release": 'ID=fedora\nPRETTY_NAME="Fedora 40"\n'})
    result = system_info.run(scenario.probe(tmp_path))
    assert result.status is Status.WARN
    assert "written for Ubuntu" in result.explanation


def test_system_info_ubuntu_derivative_is_fine(tmp_path):
    scenario = healthy().but(
        files={"/etc/os-release": 'ID=linuxmint\nID_LIKE="ubuntu debian"\nNAME="Linux Mint"\n'}
    )
    assert system_info.run(scenario.probe(tmp_path)).status is Status.PASS


def test_system_info_missing_everything(tmp_path):
    result = system_info.run(
        no_gpu()
        .but(files={"/etc/os-release": None, "/proc/sys/kernel/osrelease": None})
        .probe(tmp_path)
    )
    assert result.status is Status.WARN
    assert "Unknown Linux, kernel unknown" in result.summary


def test_system_info_in_container(tmp_path):
    result = system_info.run(healthy().but(files={"/.dockerenv": ""}).probe(tmp_path))
    assert result.status is Status.PASS
    assert "docker container" in result.summary
    assert result.facts["container"] == "docker"


def test_gpu_present_healthy(tmp_path):
    result = gpu_present.run(healthy().probe(tmp_path))
    assert result.status is Status.PASS
    # The card's HDMI audio function (same vendor, class 0x0403) is not a GPU.
    assert result.summary == "1 NVIDIA GPU: AD102 [GeForce RTX 4090] (0000:01:00.0)"
    assert result.facts["pci_ids"] == "10de:2684"


def test_gpu_present_3d_controller_and_unknown_name(tmp_path):
    scenario = healthy().but(
        files={**pci("0000:02:00.0", "10de", "abcd", "030200"), "/usr/share/misc/pci.ids": None}
    )
    result = gpu_present.run(scenario.probe(tmp_path))
    assert result.status is Status.PASS
    assert result.facts["gpu_count"] == "2"
    assert "device 10de:abcd (0000:02:00.0)" in result.summary


def test_no_gpu(tmp_path):
    result = gpu_present.run(no_gpu().probe(tmp_path))
    assert result.status is Status.FAIL
    assert result.summary == "No NVIDIA GPU found"
    assert "passed through" in result.explanation


def test_no_pci_devices_falls_back_to_lspci(tmp_path):
    lspci = "01:00.0 3D controller [0302]: NVIDIA Corporation AD107M [10de:28e0] (rev a1)\n"
    scenario = no_gpu().but(
        files={k: None for k in no_gpu().files if k.startswith("/sys/bus/pci")},
        commands={("lspci", "-nn"): CommandResult(0, lspci, "")},
    )
    result = gpu_present.run(scenario.probe(tmp_path))
    assert result.status is Status.PASS
    assert result.evidence[0].source == "lspci -nn"


def test_no_pci_devices_at_all(tmp_path):
    scenario = no_gpu().but(files={k: None for k in no_gpu().files if k.startswith("/sys/bus/pci")})
    result = gpu_present.run(scenario.probe(tmp_path))
    assert result.status is Status.FAIL
    assert "containers" in result.explanation
