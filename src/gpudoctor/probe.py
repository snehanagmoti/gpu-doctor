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
  Inside a snap it is raised as ``ConfinementError`` instead, because sudo
  does not lift snap confinement.

Snaps
-----
Inside a strictly confined snap, ``/`` is the base snap with some host
directories bind-mounted on top. ``SystemProbe.path()`` sends reads of
everything else to the host's real files under /var/lib/snapd/hostfs, so the
checks never accidentally inspect the base snap's own dpkg database.
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


class ConfinementError(PermissionError):
    """A file the snap's strict confinement does not let us read.

    A subclass of PermissionError so code that does not care treats it the
    same way, while the runner can explain it properly instead of telling the
    user to use sudo (which would not help inside a snap).
    """


# Inside a strictly confined snap the mount namespace is built from the base
# snap (core24), with only some directories bind-mounted from the host (see
# snapd's cmd/snap-confine/mount-support.c). These are the ones we read that
# come from the host; everything else (/var/lib/dpkg, /var/lib/dkms,
# /usr/local, /usr/lib/<triplet>) is the *base snap's* copy in the namespace,
# and the host's copy is only reachable under /var/lib/snapd/hostfs.
SNAP_SHARED_PREFIXES = (
    "/proc/",
    "/sys/",
    "/dev/",
    "/run/",
    "/etc/",
    "/lib/modules/",
    "/usr/lib/modules/",
    "/usr/src/",
    "/var/log/",
    "/var/lib/snapd/",
    "/snap/",
)
# /etc comes from the host, but os-release is a symlink into /usr/lib, which
# would resolve inside the base snap ("Ubuntu Core 24"). Read it via hostfs.
SNAP_HOSTFS_EXCEPTIONS = ("/etc/os-release",)
SNAP_HOSTFS = "/var/lib/snapd/hostfs"


class SystemProbe(abc.ABC):
    """Read-only view of a Linux system. Paths are always absolute ("/proc/...")."""

    def __init__(self, root: str | os.PathLike[str] = "/", host_prefix: str | None = None) -> None:
        self.root = Path(root)
        # False when commands must not run (HostProbe inspecting a --root image).
        self.commands_enabled = True
        # Set inside a snap: where the host's real root is visible.
        self.host_prefix = host_prefix

    @property
    def confined(self) -> bool:
        return self.host_prefix is not None

    # -- filesystem -------------------------------------------------------

    def path(self, path: str) -> Path:
        """Map an absolute system path onto this probe's root directory."""
        if not path.startswith("/"):
            raise ValueError(f"probe paths must be absolute, got {path!r}")
        if self.host_prefix and (
            path in SNAP_HOSTFS_EXCEPTIONS or not (path + "/").startswith(SNAP_SHARED_PREFIXES)
        ):
            path = self.host_prefix + path
        return self.root / path.lstrip("/")

    def _denied(self, path: str) -> bool:
        """Hook for test doubles to simulate unreadable files."""
        return False

    def _permission_error(self, path: str, exc: OSError | None = None) -> PermissionError:
        if self.confined:
            return ConfinementError(13, "Not allowed by snap confinement", path)
        return PermissionError(13, "Permission denied", path)

    def read_bytes(self, path: str) -> bytes | None:
        # Read in modest chunks. A single read(64 MiB) fails with ENOMEM on
        # /proc/sys files, because the sysctl handler tries to allocate a
        # kernel buffer as large as the requested read size.
        if self._denied(path):
            raise self._permission_error(path)
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
        except PermissionError as exc:
            raise self._permission_error(path, exc) from exc
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
        other than ``/`` (tests, ``--root``, a snap's hostfs), resolving such a
        link naively would look at the wrong ``/usr/src``. Only the last path
        component is followed, which is all the checks need.
        """
        resolved = self.path(path)
        for _ in range(40):  # same loop limit the kernel uses (ELOOP)
            if not resolved.is_symlink():
                break
            target = os.readlink(resolved)
            resolved = self.path(target) if target.startswith("/") else resolved.parent / target
        return resolved

    def exists(self, path: str) -> bool:
        """True if ``path`` exists. A dangling symlink counts as missing."""
        return self._resolve(path).exists()

    def is_dir(self, path: str) -> bool:
        return self._resolve(path).is_dir()

    def list_dir(self, path: str) -> list[str]:
        """Sorted entry names in ``path``; ``[]`` if it is missing or not a dir."""
        if self._denied(path):
            raise self._permission_error(path)
        try:
            return sorted(os.listdir(self.path(path)))
        except (FileNotFoundError, NotADirectoryError):
            return []
        except PermissionError as exc:
            raise self._permission_error(path, exc) from exc

    def glob(self, pattern: str) -> list[str]:
        """Absolute system paths matching ``pattern`` (sorted), e.g. ``/etc/modprobe.d/*.conf``.

        ``Path.glob`` silently skips directories it cannot read, which would
        turn "not allowed to look" into "nothing there". So the fixed part of
        the pattern is listed first, letting a PermissionError surface.
        """
        if not pattern.startswith("/"):
            raise ValueError(f"glob patterns must be absolute, got {pattern!r}")
        parts = pattern.strip("/").split("/")
        fixed = []
        for part in parts:
            if any(ch in part for ch in "*?["):
                break
            fixed.append(part)
        base = "/" + "/".join(fixed)
        rest = "/".join(parts[len(fixed) :])
        if not rest:
            return [base] if self.exists(base) else []
        self.list_dir(base)  # raises PermissionError if the directory is unreadable
        mapped = self.path(base)
        prefix = base.rstrip("/")
        return sorted(f"{prefix}/{m.relative_to(mapped)}" for m in mapped.glob(rest))

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
        in_snap = bool(os.environ.get("SNAP")) and Path(root) == Path("/")
        hostfs = SNAP_HOSTFS if in_snap and os.path.isdir(SNAP_HOSTFS) else None
        super().__init__(root, host_prefix=hostfs)
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
        host_prefix: str | None = None,
    ) -> None:
        super().__init__(root, host_prefix=host_prefix)
        self.commands = dict(commands or {})
        self.env = dict(env or {})
        self._machine = machine
        # Paths that raise PermissionError, to simulate running without root.
        # (chmod 000 does not work for this when the tests run as root.)
        self.deny = frozenset(deny)
        self.calls: list[tuple[str, ...]] = []  # spy: commands that were run

    def _denied(self, path: str) -> bool:
        return path in self.deny

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
