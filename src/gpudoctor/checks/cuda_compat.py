"""Check 11: is the installed CUDA toolkit supported by the installed driver?

The driver provides libcuda (the CUDA driver API); the toolkit (nvcc,
libcudart) is installed separately, often several versions side by side
under /usr/local/cuda-X.Y. Two thresholds matter, both from NVIDIA's CUDA
release notes and stored in data/cuda_driver_matrix.json:

* toolkit driver: the driver version each toolkit release ships with; full
  support for every feature of that toolkit.
* minor version compatibility: since CUDA 11, an application built with any
  X.y toolkit runs on a driver that supports X.0, with limits (e.g. PTX JIT
  for newer features fails). Below this minimum the toolkit does not work.

Note that the "CUDA Version" printed by nvidia-smi is the newest CUDA the
*driver* supports, not the toolkit that is installed.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from importlib import resources
from typing import Any

from ..model import CheckResult, Evidence, Status
from ..probe import SystemProbe
from ..runner import Check
from ..system import installed_packages, nvidia_kernel_version, upstream_version, version_tuple

ID = "cuda_compat"


@dataclass(frozen=True)
class Toolkit:
    version: str  # "12.4.1"
    source: str  # where we found it


@dataclass(frozen=True)
class Requirement:
    toolkit_driver: str | None  # None when the release is not in our table
    minor_compat_driver: str | None
    matched_release: str | None


@lru_cache(maxsize=1)
def load_matrix() -> dict[str, Any]:
    text = resources.files("gpudoctor").joinpath("data/cuda_driver_matrix.json").read_text()
    data: dict[str, Any] = json.loads(text)
    return data


def requirement(version: str, matrix: dict[str, Any] | None = None) -> Requirement:
    matrix = matrix or load_matrix()
    want = version_tuple(version)
    major_minor = want[:2]
    patch = want[2] if len(want) > 2 else 0

    # Exact release, else the newest known update of the same X.Y that is not
    # newer than ours (12.6.4 -> 12.6.3), else unknown.
    candidates = [
        (version_tuple(rel), drv)
        for rel, drv in matrix["toolkit_driver"].items()
        if version_tuple(rel)[:2] == major_minor and version_tuple(rel)[2] <= patch
    ]
    best = max(candidates, default=None)
    minor = None
    for entry in matrix["minor_version_compatibility"]:
        start = version_tuple(entry["cuda_from"])
        if want[:1] == start[:1] and want[:2] >= start[:2]:
            minor = entry["min_driver"]
            break
    return Requirement(
        toolkit_driver=best[1] if best else None,
        minor_compat_driver=minor,
        matched_release=".".join(map(str, best[0])) if best else None,
    )


def _from_version_json(text: str) -> str | None:
    try:
        data = json.loads(text)
    except ValueError:
        return None
    version = data.get("cuda", {}).get("version") if isinstance(data, dict) else None
    return version if isinstance(version, str) else None


def find_toolkits(probe: SystemProbe) -> list[Toolkit]:
    found: dict[str, Toolkit] = {}

    def add(version: str | None, source: str) -> None:
        if version and re.match(r"^\d+\.\d+", version) and version not in found:
            found[version] = Toolkit(version, source)

    # NVIDIA's installers: /usr/local/cuda-X.Y/version.json (CUDA >= 11.1)
    # or version.txt ("CUDA Version 10.2.89") for older releases.
    for path in probe.glob("/usr/local/cuda-*/version.json"):
        add(_from_version_json(probe.read_text(path) or ""), path)
    for path in probe.glob("/usr/local/cuda-*/version.txt"):
        match = re.search(r"CUDA Version (\d+\.\d+(?:\.\d+)?)", probe.read_text(path) or "")
        add(match.group(1) if match else None, path)

    # Ubuntu's own package: nvidia-cuda-toolkit 12.0.140~12.0.1-4build4 (noble)
    # or 11.5.1-1ubuntu1 (jammy). The part after "~" is the toolkit release.
    pkg = installed_packages(probe).get("nvidia-cuda-toolkit")
    if pkg:
        add(
            upstream_version(pkg.version).split("~")[-1],
            "/var/lib/dpkg/status (nvidia-cuda-toolkit)",
        )

    if not found:
        result = probe.run(["nvcc", "--version"])
        if result is not None and result.returncode == 0:
            match = re.search(r"release (\d+\.\d+)", result.stdout)
            add(match.group(1) if match else None, "nvcc --version")
    return sorted(found.values(), key=lambda t: version_tuple(t.version))


def driver_version(probe: SystemProbe) -> tuple[str | None, str]:
    version = nvidia_kernel_version(probe)
    if version:
        return version, "/proc/driver/nvidia/version"
    for name, pkg in installed_packages(probe).items():
        if re.match(r"^libnvidia-compute-\d+(-server)?$", name):
            return upstream_version(pkg.version), f"/var/lib/dpkg/status ({name})"
    return None, ""


def _assess(toolkit: Toolkit, driver: str) -> tuple[Status, str, str]:
    req = requirement(toolkit.version)
    have = version_tuple(driver)
    major = toolkit.version.split(".")[0]
    if req.toolkit_driver is None:
        if req.minor_compat_driver and have >= version_tuple(req.minor_compat_driver):
            return (
                Status.PASS,
                f"CUDA {toolkit.version} is not in gpu-doctor's table yet, but driver "
                f"{driver} meets the CUDA {major}.x minimum ({req.minor_compat_driver})",
                "",
            )
        return (
            Status.WARN,
            f"CUDA {toolkit.version} is newer than gpu-doctor's compatibility table",
            "",
        )
    if have >= version_tuple(req.toolkit_driver):
        return (
            Status.PASS,
            f"CUDA {toolkit.version} is fully supported (needs driver >= {req.toolkit_driver})",
            "",
        )
    branch = req.toolkit_driver.split(".")[0]
    if req.minor_compat_driver and have >= version_tuple(req.minor_compat_driver):
        return (
            Status.WARN,
            f"CUDA {toolkit.version} runs only in minor-version-compatibility mode on "
            f"driver {driver} (full support needs >= {req.toolkit_driver})",
            branch,
        )
    return (
        Status.FAIL,
        f"CUDA {toolkit.version} needs driver >= {req.minor_compat_driver or req.toolkit_driver}, "
        f"but {driver} is installed",
        branch,
    )


def run(probe: SystemProbe) -> CheckResult:
    toolkits = find_toolkits(probe)
    if not toolkits:
        return CheckResult(
            ID,
            Status.SKIP,
            "No CUDA toolkit installed (not needed to run most CUDA applications)",
            explanation=(
                "PyTorch, TensorFlow and most CUDA programs ship their own CUDA runtime "
                "and only need the driver. The toolkit (nvcc) is only needed to compile CUDA code."
            ),
        )
    driver, driver_source = driver_version(probe)
    evidence = [Evidence(t.source, f"CUDA {t.version}") for t in toolkits]
    if driver is None:
        return CheckResult(
            ID,
            Status.SKIP,
            "Driver version unknown, so CUDA compatibility cannot be checked",
            evidence=tuple(evidence),
        )
    evidence.append(Evidence(driver_source, driver))
    matrix = load_matrix()
    evidence.append(
        Evidence("data/cuda_driver_matrix.json", f"last updated {matrix['last_updated']}")
    )

    assessed = [(t, *_assess(t, driver)) for t in toolkits]
    worst = max(assessed, key=lambda a: a[1].severity)
    _, status, summary, branch = worst
    facts = {
        "driver_version": driver,
        "cuda_toolkits": " ".join(t.version for t in toolkits),
    }
    if status is Status.PASS:
        if len(toolkits) > 1:
            versions = ", ".join(t.version for t in toolkits)
            summary = f"All installed CUDA toolkits ({versions}) support driver {driver}"
        return CheckResult(ID, Status.PASS, summary, evidence=tuple(evidence), facts=facts)

    others = [a[2] for a in assessed if a is not worst and a[1] is not Status.PASS]
    explanation = (
        "Either upgrade the driver to a branch that supports this CUDA release, or "
        "install an older CUDA toolkit that matches your driver. Minor-version "
        "compatibility lets applications run, but features that need a newer driver "
        "(such as JIT-compiling PTX for newer GPUs) fail."
    )
    if others:
        explanation += " Also: " + "; ".join(others) + "."
    fixes = ("ubuntu-drivers list", f"sudo apt install nvidia-driver-{branch}") if branch else ()
    return CheckResult(
        ID,
        status,
        summary,
        explanation=explanation,
        fixes=fixes,
        evidence=tuple(evidence),
        facts=facts,
    )


CHECK = Check(
    id=ID, title="CUDA toolkit compatible with driver", func=run, requires=("gpu_present",)
)
