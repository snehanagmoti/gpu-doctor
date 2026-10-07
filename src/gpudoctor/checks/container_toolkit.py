"""Check 12 (optional): can Docker containers use the GPU?

Needs the NVIDIA Container Toolkit, which comes from NVIDIA's own apt
repository, and the nvidia runtime registered with Docker (NVIDIA's install
guide does this with ``nvidia-ctk runtime configure``). Skipped when Docker
is not installed.
"""

from __future__ import annotations

import json

from ..model import CheckResult, Evidence, Status
from ..probe import SystemProbe
from ..runner import Check
from ..system import container_type, installed_packages

ID = "container_toolkit"

INSTALL_GUIDE = (
    "https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html"
)
DAEMON_JSON = "/etc/docker/daemon.json"
DOCKER_PACKAGES = ("docker-ce", "docker.io", "moby-engine")


def run(probe: SystemProbe) -> CheckResult:
    if container_type(probe):
        return CheckResult(
            ID, Status.SKIP, "Inside a container; the toolkit is configured on the host"
        )
    packages = installed_packages(probe)
    docker = [p for p in DOCKER_PACKAGES if p in packages]
    if not docker:
        return CheckResult(ID, Status.SKIP, "Docker is not installed")

    toolkit = packages.get("nvidia-container-toolkit")
    evidence = [
        Evidence(
            "/var/lib/dpkg/status",
            f"{docker[0]} installed; nvidia-container-toolkit "
            + (toolkit.version if toolkit else "not installed"),
        ),
    ]
    if toolkit is None:
        return CheckResult(
            ID,
            Status.WARN,
            "Docker is installed but the NVIDIA Container Toolkit is not",
            explanation=(
                "Containers cannot use the GPU ('docker run --gpus all' fails) without it. "
                f"Add NVIDIA's apt repository as described in {INSTALL_GUIDE}, then install "
                "and configure the toolkit."
            ),
            fixes=(
                "sudo apt install nvidia-container-toolkit",
                "sudo nvidia-ctk runtime configure --runtime=docker",
                "sudo systemctl restart docker",
            ),
            evidence=tuple(evidence),
        )

    runtimes: dict[str, object] = {}
    text = probe.read_text(DAEMON_JSON)
    if text:
        try:
            data = json.loads(text)
            if isinstance(data, dict) and isinstance(data.get("runtimes"), dict):
                runtimes = data["runtimes"]
        except ValueError:
            evidence.append(Evidence(DAEMON_JSON, "not valid JSON"))
    evidence.append(Evidence(DAEMON_JSON, "runtimes: " + (", ".join(runtimes) or "none")))
    if "nvidia" not in runtimes:
        return CheckResult(
            ID,
            Status.WARN,
            "The nvidia runtime is not registered with Docker",
            explanation=(
                "The toolkit is installed but Docker's daemon.json has no 'nvidia' runtime, "
                "so '--runtime=nvidia' and Compose files that use it will fail."
            ),
            fixes=(
                "sudo nvidia-ctk runtime configure --runtime=docker",
                "sudo systemctl restart docker",
            ),
            evidence=tuple(evidence),
        )
    return CheckResult(
        ID,
        Status.PASS,
        f"NVIDIA Container Toolkit {toolkit.version} is set up for Docker",
        evidence=tuple(evidence),
    )


CHECK = Check(id=ID, title="Docker GPU support", func=run, requires=("gpu_present",))
