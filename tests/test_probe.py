import os

import pytest

from fsbuilder import Dir, Symlink, materialise
from gpudoctor.probe import CommandResult, FakeProbe, HostProbe


@pytest.fixture
def root(tmp_path):
    materialise(
        tmp_path,
        {
            "/proc/modules": "nvidia 1 0 - Live 0x0\n",
            "/etc/modprobe.d/a.conf": "blacklist nouveau\n",
            "/etc/modprobe.d/b.conf": "",
            "/usr/src/linux-headers-6.8.0-45-generic": Dir(),
            # Absolute symlink, like the real /lib/modules/<k>/build link.
            "/lib/modules/6.8.0-45-generic/build": Symlink(
                "/usr/src/linux-headers-6.8.0-45-generic"
            ),
            "/lib/modules/6.8.0-47-generic/build": Symlink(
                "/usr/src/linux-headers-6.8.0-47-generic"
            ),
            "/bin.dat": b"\x06\x00\x00\x00\x01\xff",
        },
    )
    return tmp_path


def test_read_text_and_missing_files(root):
    probe = HostProbe(root)
    assert probe.read_text("/proc/modules") == "nvidia 1 0 - Live 0x0\n"
    assert probe.read_text("/nope") is None
    assert probe.read_text("/proc/modules/child") is None  # NotADirectoryError
    assert probe.read_bytes("/bin.dat") == b"\x06\x00\x00\x00\x01\xff"
    assert probe.read_text("/bin.dat") is not None  # undecodable bytes never crash
    assert probe.read_text("/etc/modprobe.d") is None  # a directory, not a file


def test_paths_must_be_absolute(root):
    probe = HostProbe(root)
    with pytest.raises(ValueError):
        probe.read_text("proc/modules")
    with pytest.raises(ValueError):
        probe.glob("etc/*")


def test_list_dir_and_glob(root):
    probe = HostProbe(root)
    assert probe.list_dir("/etc/modprobe.d") == ["a.conf", "b.conf"]
    assert probe.list_dir("/missing") == []
    assert probe.glob("/etc/modprobe.d/*.conf") == [
        "/etc/modprobe.d/a.conf",
        "/etc/modprobe.d/b.conf",
    ]


def test_absolute_symlinks_resolve_inside_root(root):
    probe = HostProbe(root)
    # Must resolve to <root>/usr/src/..., not to the real /usr/src on this machine.
    assert probe.exists("/lib/modules/6.8.0-45-generic/build")
    assert probe.is_dir("/lib/modules/6.8.0-45-generic/build")
    # Dangling link: the headers package for 6.8.0-47 is not installed.
    assert not probe.exists("/lib/modules/6.8.0-47-generic/build")


def test_host_probe_disables_commands_for_foreign_root(root):
    probe = HostProbe(root)
    assert probe.which("sh") is None
    assert probe.run(["sh", "-c", "true"]) is None


def test_host_probe_runs_real_commands():
    probe = HostProbe("/")
    result = probe.run(["sh", "-c", "echo out; echo err >&2; exit 3"])
    assert result == CommandResult(3, "out\n", "err\n")
    assert probe.run(["definitely-not-a-real-binary-xyz"]) is None


def test_host_probe_timeout_does_not_raise():
    result = HostProbe("/").run(["sleep", "5"], timeout=0.1)
    assert result is not None
    assert result.returncode == -1
    assert "timed out" in result.stderr


def test_host_probe_machine_and_env(monkeypatch):
    probe = HostProbe("/")
    assert probe.machine() == os.uname().machine or probe.machine()
    monkeypatch.setenv("GPU_DOCTOR_TEST", "1")
    assert probe.getenv("GPU_DOCTOR_TEST") == "1"


def test_fake_probe_commands_and_spy(root):
    probe = FakeProbe(
        root,
        commands={("nvidia-smi", "-L"): CommandResult(0, "GPU 0\n", "")},
        env={"SNAP": "/snap/x/1"},
        machine="aarch64",
    )
    assert probe.which("nvidia-smi") == "/usr/bin/nvidia-smi"
    assert probe.which("dkms") is None
    assert probe.run(["nvidia-smi", "-L"]) == CommandResult(0, "GPU 0\n", "")
    assert probe.run(["dkms", "status"]) is None
    assert probe.calls == [("nvidia-smi", "-L"), ("dkms", "status")]
    assert probe.getenv("SNAP") == "/snap/x/1"
    assert probe.machine() == "aarch64"
    with pytest.raises(AssertionError, match="unscripted"):
        probe.run(["nvidia-smi", "--typo"])


def test_fake_probe_can_simulate_permission_denied(root):
    probe = FakeProbe(root, deny={"/proc/modules", "/etc/modprobe.d"})
    with pytest.raises(PermissionError):
        probe.read_text("/proc/modules")
    with pytest.raises(PermissionError):
        probe.list_dir("/etc/modprobe.d")
