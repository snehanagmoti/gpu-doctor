"""Branches of individual checks that the scenario table does not reach."""

import pytest

from gpudoctor.checks import (
    container_toolkit,
    cuda_compat,
    driver_package,
    kernel_headers,
    module_build,
    nouveau,
    nvidia_smi,
    prime,
    secure_boot,
    version_mismatch,
)
from gpudoctor.model import Status
from gpudoctor.probe import CommandResult

from scenarios import (
    KERNEL,
    MOK_KEY,
    MOK_TEST_KEY,
    NVIDIA_SMI_QUERY,
    SECURE_BOOT_VAR,
    docker_without_toolkit,
    healthy,
    healthy_dkms,
    hybrid_integrated_only,
    in_docker,
    in_snap,
    no_driver,
    nvrm,
    secure_boot_unsigned,
)


def run(check, scenario, tmp_path):
    return check.run(scenario.probe(tmp_path))


# -- driver_package ----------------------------------------------------------


def test_driver_package_without_dpkg(tmp_path):
    scenario = healthy()
    scenario = type(scenario)(files=scenario.files, packages=None)
    result = run(driver_package, scenario, tmp_path)
    assert result.status is Status.SKIP
    assert "dpkg" in result.summary


def test_driver_package_libraries_without_metapackage(tmp_path):
    scenario = healthy().but(packages={"nvidia-driver-550": None})
    result = run(driver_package, scenario, tmp_path)
    assert result.status is Status.WARN
    assert "without a driver package" in result.summary


def test_driver_package_open_variant(tmp_path):
    scenario = healthy().but(packages={"nvidia-driver-550": None, "nvidia-driver-550-open": "550"})
    result = run(driver_package, scenario, tmp_path)
    assert result.status is Status.PASS
    assert "open kernel modules" in result.summary
    assert result.facts["driver_variant"] == "open"


# -- module_build -----------------------------------------------------------


def test_module_build_dkms_built_but_not_installed(tmp_path):
    scenario = healthy_dkms().but(files={f"/lib/modules/{KERNEL}/updates/dkms/nvidia.ko.zst": None})
    result = run(module_build, scenario, tmp_path)
    assert result.status is Status.WARN
    assert result.fixes == ("sudo dkms install nvidia/550.120 -k $(uname -r)",)


def test_module_build_points_at_make_log(tmp_path):
    from scenarios import dkms_missing_after_kernel_upgrade

    scenario = dkms_missing_after_kernel_upgrade().but(
        files={"/var/lib/dkms/nvidia/550.120/build/make.log": "error: implicit declaration\n"}
    )
    result = run(module_build, scenario, tmp_path)
    assert result.status is Status.FAIL
    assert result.fixes[0] == "less /var/lib/dkms/nvidia/550.120/build/make.log"
    assert "built only for: 6.8.0-45-generic" in result.explanation


def test_module_build_driver_but_no_module_anywhere(tmp_path):
    scenario = healthy().but(
        packages={
            f"linux-modules-nvidia-550-{KERNEL}": None,
            "linux-modules-nvidia-550-generic": None,
        },
        files={f"/lib/modules/{KERNEL}/kernel/nvidia-550srv/nvidia.ko": None},
    )
    result = run(module_build, scenario, tmp_path)
    assert result.status is Status.FAIL
    assert result.fixes == ("sudo ubuntu-drivers install", "sudo reboot")


def test_module_build_unknown_kernel(tmp_path):
    result = run(module_build, healthy().but(files={"/proc/sys/kernel/osrelease": None}), tmp_path)
    assert result.status is Status.SKIP


# -- kernel_headers ---------------------------------------------------------


def test_headers_skip_in_container_and_unknown_kernel(tmp_path):
    assert run(kernel_headers, in_docker(), tmp_path / "a").status is Status.SKIP
    scenario = healthy_dkms().but(files={"/proc/sys/kernel/osrelease": None})
    assert run(kernel_headers, scenario, tmp_path / "b").status is Status.SKIP


def test_headers_metapackage_missing_warns(tmp_path):
    scenario = healthy_dkms().but(packages={"linux-headers-generic": None})
    result = run(kernel_headers, scenario, tmp_path)
    assert result.status is Status.WARN
    assert result.fixes == ("sudo apt install linux-headers-generic",)


def test_headers_hwe_metapackage_counts(tmp_path):
    scenario = healthy_dkms().but(
        packages={"linux-headers-generic": None, "linux-headers-generic-hwe-22.04": "6.8.0.45"}
    )
    assert run(kernel_headers, scenario, tmp_path).status is Status.PASS


# -- nouveau ----------------------------------------------------------------


def test_nouveau_blacklisted_but_loaded_means_stale_initramfs(tmp_path):
    from scenarios import nouveau_loaded

    scenario = nouveau_loaded().but(files={"/etc/modprobe.d/bl.conf": "blacklist nouveau\n"})
    result = run(nouveau, scenario, tmp_path)
    assert result.status is Status.FAIL
    assert result.fixes == ("sudo update-initramfs -u", "sudo reboot")


def test_nouveau_blocked_on_kernel_cmdline(tmp_path):
    scenario = healthy().but(
        files={
            "/lib/modprobe.d/nvidia-graphics-drivers.conf": None,
            "/proc/cmdline": "root=/dev/sda1 modprobe.blacklist=nouveau quiet",
        }
    )
    result = run(nouveau, scenario, tmp_path)
    assert result.status is Status.PASS
    assert "/proc/cmdline (modprobe.blacklist=nouveau)" in result.summary


# -- secure_boot ------------------------------------------------------------


def test_secure_boot_unreadable_variable(tmp_path):
    scenario = healthy().but(files={SECURE_BOOT_VAR: b"\x06"})
    assert run(secure_boot, scenario, tmp_path).status is Status.SKIP


def test_secure_boot_enrolled_key_but_module_not_loaded(tmp_path):
    scenario = secure_boot_unsigned().but(
        commands={MOK_TEST_KEY: CommandResult(0, f"{MOK_KEY} is already enrolled\n", "")}
    )
    result = run(secure_boot, scenario, tmp_path)
    assert result.status is Status.WARN
    assert result.facts["mok_enrolled"] == "yes"


def test_secure_boot_no_mok_key_yet(tmp_path):
    scenario = secure_boot_unsigned().but(files={MOK_KEY: None})
    result = run(secure_boot, scenario, tmp_path)
    assert result.status is Status.FAIL
    assert result.fixes[0] == "sudo update-secureboot-policy --new-key"
    assert result.facts["mok_enrolled"] == "unknown"


def test_secure_boot_reports_module_signer(tmp_path):
    module = f"/lib/modules/{KERNEL}/updates/dkms/nvidia.ko.zst"
    scenario = secure_boot_unsigned().but(
        commands={("modinfo", "-F", "signer", module): CommandResult(0, "\n", "")}
    )
    result = run(secure_boot, scenario, tmp_path)
    assert any(e.value == "unsigned" for e in result.evidence)


def test_secure_boot_in_snap_explains_missing_mokutil(tmp_path):
    scenario = secure_boot_unsigned().but(
        commands={MOK_TEST_KEY: None}, env={"SNAP": "/snap/gpu-doctor/1"}
    )
    result = run(secure_boot, scenario, tmp_path)
    assert result.status is Status.FAIL
    assert "cannot call mokutil" in result.explanation


def test_secure_boot_mokutil_unexpected_output(tmp_path):
    scenario = secure_boot_unsigned().but(
        commands={MOK_TEST_KEY: CommandResult(255, "", "EFI error")}
    )
    result = run(secure_boot, scenario, tmp_path)
    assert result.status is Status.FAIL
    assert result.facts["mok_enrolled"] == "unknown"


# -- version_mismatch ------------------------------------------------------


def test_version_mismatch_falls_back_to_dpkg(tmp_path):
    scenario = healthy().but(
        files={
            "/usr/lib/x86_64-linux-gnu/libnvidia-ml.so.550.120": None,
            "/usr/lib/x86_64-linux-gnu/libnvidia-ml.so.1": None,
        }
    )
    result = run(version_mismatch, scenario, tmp_path)
    assert result.status is Status.PASS
    assert "libnvidia-compute" in result.evidence[1].source


def test_version_mismatch_no_libraries(tmp_path):
    scenario = healthy().but(
        files={
            "/usr/lib/x86_64-linux-gnu/libnvidia-ml.so.550.120": None,
            "/usr/lib/x86_64-linux-gnu/libnvidia-ml.so.1": None,
        },
        packages={"libnvidia-compute-550": None},
    )
    assert run(version_mismatch, scenario, tmp_path).status is Status.SKIP


def test_version_mismatch_no_module(tmp_path):
    scenario = healthy().but(files={"/proc/driver/nvidia/version": None})
    assert run(version_mismatch, scenario, tmp_path).status is Status.SKIP


def test_version_mismatch_arm64_library_path(tmp_path):
    from scenarios import Scenario

    base = healthy().but(
        files={
            "/usr/lib/x86_64-linux-gnu/libnvidia-ml.so.550.120": None,
            "/usr/lib/aarch64-linux-gnu/libnvidia-ml.so.550.120": b"",
        },
        packages={"libnvidia-compute-550": None},
    )
    scenario = Scenario(files=base.files, packages=base.packages, machine="aarch64")
    result = run(version_mismatch, scenario, tmp_path)
    assert result.status is Status.PASS
    assert result.evidence[1].source.startswith("/usr/lib/aarch64-linux-gnu/")


# -- nvidia_smi -------------------------------------------------------------


def test_nvidia_smi_missing_with_driver_suggests_utils(tmp_path):
    result = run(nvidia_smi, healthy().but(commands={NVIDIA_SMI_QUERY: None}), tmp_path)
    assert result.status is Status.WARN
    assert result.fixes == ("sudo apt install nvidia-utils-550",)


def test_nvidia_smi_missing_without_driver(tmp_path):
    assert run(nvidia_smi, no_driver(), tmp_path).status is Status.SKIP


def test_nvidia_smi_timeout(tmp_path):
    scenario = healthy().but(
        commands={NVIDIA_SMI_QUERY: CommandResult(-1, "", "timed out after 20s")}
    )
    result = run(nvidia_smi, scenario, tmp_path)
    assert result.status is Status.WARN
    assert "did not answer" in result.summary


def test_nvidia_smi_unknown_failure_and_no_devices(tmp_path):
    scenario = healthy().but(commands={NVIDIA_SMI_QUERY: CommandResult(6, "", "")})
    result = run(nvidia_smi, scenario, tmp_path / "a")
    assert result.status is Status.FAIL
    assert result.summary == "nvidia-smi failed: exit status 6"
    scenario = healthy().but(
        commands={NVIDIA_SMI_QUERY: CommandResult(6, "No devices were found\n", "")}
    )
    result = run(nvidia_smi, scenario, tmp_path / "b")
    assert "sees no usable GPU" in result.explanation


def test_nvidia_smi_skipped_in_snap(tmp_path):
    assert run(nvidia_smi, in_snap(), tmp_path).status is Status.SKIP


# -- cuda_compat ------------------------------------------------------------


@pytest.mark.parametrize(
    ("version", "toolkit_driver", "minor", "matched"),
    [
        ("12.4.1", "550.54.15", "525.60.13", "12.4.1"),
        ("12.4", "550.54.14", "525.60.13", "12.4.0"),
        ("12.6.4", "560.35.05", "525.60.13", "12.6.3"),  # unknown update -> newest known
        ("11.0.3", "450.51.06", "450.36.06", "11.0.3"),  # 11.0 has its own minimum
        ("11.8.0", "520.61.05", "450.80.02", "11.8.0"),
        ("13.4.0", None, "580.65.06", None),  # newer than the table
        ("10.2.89", None, None, None),  # before minor version compatibility existed
    ],
)
def test_cuda_requirement_lookup(version, toolkit_driver, minor, matched):
    req = cuda_compat.requirement(version)
    assert (req.toolkit_driver, req.minor_compat_driver, req.matched_release) == (
        toolkit_driver,
        minor,
        matched,
    )


def test_cuda_matrix_has_sources_and_date():
    matrix = cuda_compat.load_matrix()
    assert matrix["sources"] and all(
        s.startswith("https://docs.nvidia.com/") for s in matrix["sources"]
    )
    assert matrix["last_updated"]


def test_cuda_minor_compat_warns(tmp_path):
    scenario = healthy().but(files={"/proc/driver/nvidia/version": nvrm("535.183.01")})
    result = run(cuda_compat, scenario, tmp_path)
    assert result.status is Status.WARN
    assert "minor-version-compatibility" in result.summary
    assert result.fixes == ("ubuntu-drivers list", "sudo apt install nvidia-driver-550")


def test_cuda_from_ubuntu_package_and_version_txt(tmp_path):
    scenario = healthy().but(
        files={
            "/usr/local/cuda-12.4/version.json": None,
            "/usr/local/cuda": None,
            "/usr/local/cuda-10.2/version.txt": "CUDA Version 10.2.89\n",
        },
        packages={"nvidia-cuda-toolkit": "12.0.140~12.0.1-4build4"},
    )
    result = run(cuda_compat, scenario, tmp_path)
    assert result.facts["cuda_toolkits"] == "10.2.89 12.0.1"
    # 10.2 is outside the table: reported, but not treated as a failure.
    assert result.status is Status.WARN
    assert "newer than gpu-doctor's compatibility table" in result.summary


def test_cuda_from_nvcc_only(tmp_path):
    scenario = healthy().but(
        files={"/usr/local/cuda-12.4/version.json": None, "/usr/local/cuda": None},
        commands={
            ("nvcc", "--version"): CommandResult(
                0, "Cuda compilation tools, release 12.2, V12.2.140\n", ""
            )
        },
    )
    result = run(cuda_compat, scenario, tmp_path)
    assert result.status is Status.PASS
    assert result.evidence[0].source == "nvcc --version"


def test_cuda_bad_version_json_is_ignored(tmp_path):
    scenario = healthy().but(files={"/usr/local/cuda-12.4/version.json": "{not json"})
    assert run(cuda_compat, scenario, tmp_path).status is Status.SKIP


def test_cuda_multiple_toolkits_all_ok(tmp_path):
    scenario = healthy().but(
        files={"/usr/local/cuda-12.2/version.json": '{"cuda": {"version": "12.2.2"}}'}
    )
    result = run(cuda_compat, scenario, tmp_path)
    assert result.status is Status.PASS
    assert result.summary == "All installed CUDA toolkits (12.2.2, 12.4.1) support driver 550.120"


def test_cuda_newer_than_table_but_major_ok(tmp_path):
    scenario = healthy().but(
        files={
            "/proc/driver/nvidia/version": nvrm("615.10"),
            "/usr/local/cuda-12.4/version.json": '{"cuda": {"version": "13.4.0"}}',
        }
    )
    result = run(cuda_compat, scenario, tmp_path)
    assert result.status is Status.PASS
    assert "not in gpu-doctor's table yet" in result.summary


def test_cuda_driver_unknown(tmp_path):
    scenario = healthy().but(
        files={"/proc/driver/nvidia/version": None}, packages={"libnvidia-compute-550": None}
    )
    assert run(cuda_compat, scenario, tmp_path).status is Status.SKIP


# -- container_toolkit -------------------------------------------------------


def test_container_toolkit_configured(tmp_path):
    scenario = docker_without_toolkit().but(
        packages={"nvidia-container-toolkit": "1.16.2-1"},
        files={"/etc/docker/daemon.json": '{"runtimes": {"nvidia": {"path": "x"}}}'},
    )
    result = run(container_toolkit, scenario, tmp_path)
    assert result.status is Status.PASS


@pytest.mark.parametrize("daemon_json", [None, "{}", "not json", '{"runtimes": []}'])
def test_container_toolkit_runtime_missing(tmp_path, daemon_json):
    scenario = docker_without_toolkit().but(
        packages={"nvidia-container-toolkit": "1.16.2-1"},
        files={"/etc/docker/daemon.json": daemon_json},
    )
    result = run(container_toolkit, scenario, tmp_path)
    assert result.status is Status.WARN
    assert "not registered" in result.summary


# -- prime ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("content", "status", "text"),
    [("on-demand\n", Status.PASS, "on-demand"), ("on\n", Status.PASS, "PRIME profile: nvidia")],
)
def test_prime_profiles(tmp_path, content, status, text):
    scenario = hybrid_integrated_only().but(files={"/etc/prime-discrete": content})
    result = run(prime, scenario, tmp_path)
    assert result.status is status
    assert text in result.summary


def test_prime_falls_back_to_prime_select(tmp_path):
    scenario = hybrid_integrated_only().but(
        files={"/etc/prime-discrete": None},
        commands={("prime-select", "query"): CommandResult(0, "nvidia\n", "")},
    )
    result = run(prime, scenario, tmp_path)
    assert result.status is Status.PASS
    assert result.evidence[0].source == "prime-select query"


def test_prime_unknown(tmp_path):
    scenario = hybrid_integrated_only().but(files={"/etc/prime-discrete": "garbage"})
    assert run(prime, scenario, tmp_path).status is Status.SKIP
