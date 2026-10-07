"""The only way checks are allowed to look at the system.

Every check receives a ``SystemProbe`` and must read files and run commands
through it, never through ``open()`` or ``subprocess`` directly. This is
dependency injection: production code passes a ``HostProbe`` rooted at ``/``,
tests pass a ``FakeProbe`` rooted at a temporary directory that contains a
hand-built fake filesystem (``/proc``, ``/sys``, ``/var/lib/dpkg``, ...) plus a
table of canned command outputs. The check code cannot tell the difference,
so a laptop without an NVIDIA GPU can test "Secure Boot on, DKMS module
missing" just as easily as "everything healthy".

Error contract
--------------
* A path that does not exist is a normal answer: ``read_text`` returns
  ``None``, ``list_dir`` returns ``[]``, ``exists`` returns ``False``.
* A command whose binary is not installed is also a normal answer: ``run``
  returns ``None``. (Inside a strictly confined snap most host binaries are
  unavailable, so this happens a lot.)
* ``PermissionError`` is *not* swallowed. It propagates to the runner, which
  turns it into a SKIP result that tells the user to retry with ``sudo``.
"""

from __future__ import annotations

import abc
import os
import shutil
import subprocess
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

# Refuse to read anything bigger than this. /var/lib/dpkg/status is the
# largest file we read (a few MB on a desktop); this guards against someone
# pointing us at /dev/zero-like files.
MAX_READ_BYTES = 64 * 1024 * 1024
READ_CHUNK_BYTES = 64 * 1024


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


class SystemProbe(abc.ABC):
    """Read-only view of a Linux system. Paths are always absolute ("/proc/...")."""

    def __init__(self, root: str | os.PathLike[str] = "/") -> None:
        self.root = Path(root)
        # False when commands must not run (HostProbe inspecting a --root image).
        self.commands_enabled = True

    # -- filesystem -------------------------------------------------------

    def path(self, path: str) -> Path:
        """Map an absolute system path onto this probe's root directory."""
        if not path.startswith("/"):
            raise ValueError(f"probe paths must be absolute, got {path!r}")
        return self.root / path.lstrip("/")

    def read_bytes(self, path: str) -> bytes | None:
        # Read in modest chunks. A single read(64 MiB) fails with ENOMEM on
        # /proc/sys files, because the sysctl handler tries to allocate a
        # kernel buffer as large as the requested read size.
        chunks: list[bytes] = []
        total = 0
        try:
            with self.path(path).open("rb", buffering=0) as handle:
                while total < MAX_READ_BYTES:
                    chunk = handle.read(READ_CHUNK_BYTES)
                    if not chunk:
                        break
                    chunks.append(chunk)
                    total += len(chunk)
        except (FileNotFoundError, NotADirectoryError, IsADirectoryError):
            return None
        return b"".join(chunks)

    def read_text(self, path: str) -> str | None:
        data = self.read_bytes(path)
        if data is None:
            return None
        # sysfs/procfs files are ASCII in practice; never crash on odd bytes.
        return data.decode("utf-8", errors="replace")

    def _resolve(self, path: str) -> Path:
        """Like ``self.path()``, but follow a final symlink *inside* the root.

        Real systems use absolute links (``/lib/modules/<k>/build`` points to
        ``/usr/src/linux-headers-<k>``). When the probe is rooted somewhere
        other than ``/`` (tests, ``--root``), resolving such a link naively
        would look at *this* machine's ``/usr/src``. Only the last path
        component is followed, which is all the checks need.
        """
        resolved = self.path(path)
        for _ in range(40):  # same loop limit the kernel uses (ELOOP)
            if not resolved.is_symlink():
                break
            target = os.readlink(resolved)
            if target.startswith("/"):
                resolved = self.root / target.lstrip("/")
            else:
                resolved = resolved.parent / target
        return resolved

    def exists(self, path: str) -> bool:
        """True if ``path`` exists. A dangling symlink counts as missing."""
        return self._resolve(path).exists()

    def is_dir(self, path: str) -> bool:
        return self._resolve(path).is_dir()

    def list_dir(self, path: str) -> list[str]:
        """Sorted entry names in ``path``; ``[]`` if it is missing or not a dir."""
        try:
            return sorted(os.listdir(self.path(path)))
        except (FileNotFoundError, NotADirectoryError):
            return []

    def glob(self, pattern: str) -> list[str]:
        """Absolute system paths matching ``pattern`` (sorted), e.g. ``/etc/modprobe.d/*.conf``."""
        if not pattern.startswith("/"):
            raise ValueError(f"glob patterns must be absolute, got {pattern!r}")
        matches = self.root.glob(pattern.lstrip("/"))
        return sorted("/" + str(m.relative_to(self.root)) for m in matches)

    # -- environment ------------------------------------------------------

    @abc.abstractmethod
    def getenv(self, name: str) -> str | None:
        """Value of an environment variable of the diagnosed environment."""

    @abc.abstractmethod
    def machine(self) -> str:
        """CPU architecture as reported by ``uname -m`` (``x86_64``, ``aarch64``)."""

    # -- commands ---------------------------------------------------------

    @abc.abstractmethod
    def which(self, name: str) -> str | None:
        """Full path of an executable, or ``None`` if it is not available."""

    @abc.abstractmethod
    def run(self, argv: list[str], timeout: float = 10.0) -> CommandResult | None:
        """Run a read-only command. ``None`` means the binary does not exist.

        A command that exceeds ``timeout`` returns ``returncode == -1`` with
        a message in ``stderr`` instead of raising, so one hung ``nvidia-smi``
        cannot take the whole tool down.
        """


class HostProbe(SystemProbe):
    """Talks to the real machine.

    With ``root="/"`` this is the normal mode. With another root it inspects
    a copied or mounted system image (``gpu-doctor --root``); commands are then
    disabled, because running this machine's binaries would describe the
    wrong system.
    """

    def __init__(self, root: str | os.PathLike[str] = "/") -> None:
        super().__init__(root)
        self.commands_enabled = self.root == Path("/")

    def getenv(self, name: str) -> str | None:
        return os.environ.get(name)

    def machine(self) -> str:
        # /proc/sys/kernel/arch exists on newer kernels and also works for
        # --root images; fall back to uname for older kernels.
        arch = self.read_text("/proc/sys/kernel/arch")
        if arch and arch.strip():
            return arch.strip()
        return os.uname().machine

    def which(self, name: str) -> str | None:
        if not self.commands_enabled:
            return None
        return shutil.which(name)

    def run(self, argv: list[str], timeout: float = 10.0) -> CommandResult | None:
        exe = self.which(argv[0])
        if exe is None:
            return None
        # LC_ALL=C so we parse English, stable output regardless of locale.
        env = dict(os.environ, LC_ALL="C")
        try:
            proc = subprocess.run(
                [exe, *argv[1:]],
                capture_output=True,
                text=True,
                errors="replace",
                timeout=timeout,
                env=env,
                check=False,
                stdin=subprocess.DEVNULL,
            )
        except subprocess.TimeoutExpired:
            return CommandResult(-1, "", f"timed out after {timeout:g}s")
        except OSError as exc:  # e.g. exec format error, permission denied
            return CommandResult(-1, "", str(exc))
        return CommandResult(proc.returncode, proc.stdout, proc.stderr)


class FakeProbe(SystemProbe):
    """Test double: a fake filesystem tree plus canned command results.

    In test-double vocabulary this is a *fake*: a real, working
    implementation (it genuinely reads files from disk) that takes a shortcut
    (a temporary directory instead of the real ``/``).
    """

    def __init__(
        self,
        root: str | os.PathLike[str],
        commands: Mapping[tuple[str, ...], CommandResult] | None = None,
        env: Mapping[str, str] | None = None,
        machine: str = "x86_64",
        deny: Iterable[str] = (),
    ) -> None:
        super().__init__(root)
        self.commands = dict(commands or {})
        self.env = dict(env or {})
        self._machine = machine
        # Paths that raise PermissionError, to simulate running without root.
        # (chmod 000 does not work for this when the tests run as root.)
        self.deny = frozenset(deny)
        self.calls: list[tuple[str, ...]] = []  # spy: commands that were run

    def _check_denied(self, path: str) -> None:
        if path in self.deny:
            raise PermissionError(13, "Permission denied", path)

    def read_bytes(self, path: str) -> bytes | None:
        self._check_denied(path)
        return super().read_bytes(path)

    def list_dir(self, path: str) -> list[str]:
        self._check_denied(path)
        return super().list_dir(path)

    def getenv(self, name: str) -> str | None:
        return self.env.get(name)

    def machine(self) -> str:
        return self._machine

    def which(self, name: str) -> str | None:
        if any(key[0] == name for key in self.commands):
            return f"/usr/bin/{name}"
        return None

    def run(self, argv: list[str], timeout: float = 10.0) -> CommandResult | None:
        key = tuple(argv)
        self.calls.append(key)
        if key in self.commands:
            return self.commands[key]
        if self.which(argv[0]) is not None:
            # The binary "exists" but the test did not script these exact
            # arguments: fail loudly so a typo in a test is obvious.
            raise AssertionError(f"FakeProbe: unscripted command {argv!r}")
        return None
