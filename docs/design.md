# Design

## Goals

1. **Read-only.** Never change the system; only print commands.
2. **Never crash.** No GPU, no driver, a container, a VM, legacy BIOS, a
   strict snap: every case ends in a clean report, not a traceback.
3. **Explain, don't just detect.** Each finding says what is wrong, why it
   usually happens, and the exact commands that fix it.
4. **Testable without hardware.** Every situation, including Secure Boot and
   DKMS failures, is reproducible in a unit test on any laptop.
5. **Easy to package.** Python standard library only at runtime, so the
   Debian package needs nothing but `python3` and the snap stays small.

## How the NVIDIA stack fails on Ubuntu

```
 apps (CUDA, PyTorch, nvidia-smi, the desktop)
   │
 userspace libraries  libcuda.so, libnvidia-ml.so (NVML)   ← libnvidia-compute-<branch>
   │  ioctl() on /dev/nvidia*                                 must match exactly ↓
 kernel modules  nvidia, nvidia_modeset, nvidia_drm, nvidia_uvm
   │  built for ONE kernel; signed or not
 kernel (uname -r)  + Secure Boot lockdown
   │
 PCI device, vendor 0x10de
```

Almost every reported problem is two layers disagreeing:

| Symptom | Layers that disagree | Check |
|---|---|---|
| No module after a kernel upgrade | module ↔ new kernel (DKMS did not build; per-kernel prebuilt package missing) | `module_build`, `kernel_headers` |
| Module will not load with Secure Boot on | module ↔ kernel lockdown (DKMS signed with an unenrolled MOK key) | `secure_boot` |
| "Driver/library version mismatch" | libraries ↔ loaded module (upgraded on disk, old module in memory) | `version_mismatch` |
| GPU not usable at all | nvidia ↔ nouveau (both want the device) | `nouveau` |
| CUDA programs fail to start | toolkit ↔ driver | `cuda_compat` |

The module reaches the machine in one of two ways, and the checks treat them
differently:

* **Prebuilt** (`linux-modules-nvidia-<branch>-<kernel>`): built and signed
  by Canonical for each kernel; what `ubuntu-drivers install` prefers. No
  compiler or headers needed; works with Secure Boot.
* **DKMS** (`nvidia-dkms-<branch>`): source code compiled on the machine by
  DKMS for every new kernel, which needs the matching `linux-headers-*` and
  signs with the local MOK key.

## Architecture

```
cli.py ──► runner.select_checks / run_checks ──► checks/*.run(probe) ──► CheckResult
   │                       │                          │
   │                       │                          └─ system.py helpers (dpkg, DKMS, PCI, ...)
   │                       │                                    │
   └─ render.py / report.py└─ isolation, dependencies          └─ probe.SystemProbe
                                                                   ├─ HostProbe (real machine)
                                                                   └─ FakeProbe (tests)
```

| Module | Responsibility |
|---|---|
| `model.py` | `Status`, `Evidence`, `CheckResult`: frozen value objects |
| `probe.py` | the only code that touches the filesystem or runs commands |
| `system.py` | pure parsers (os-release, dpkg status, DKMS layout, lspci, pci.ids) |
| `checks/` | one module per check; `ALL_CHECKS` is the ordered registry |
| `runner.py` | dependency handling and the never-crash guarantee |
| `render.py`, `report.py` | text, JSON and redacted report output; exit codes |
| `cli.py` | argument parsing and wiring |

### Dependency injection and test doubles

A check never calls `open()` or `subprocess`. It receives a `SystemProbe`
and asks it: `probe.read_text("/proc/modules")`, `probe.run([...])`. The
dependency (access to the system) is *injected* instead of being reached for.

* In production the CLI passes `HostProbe("/")`.
* In tests, `FakeProbe(tmp_path, commands={...})` is rooted at a temporary
  directory holding a hand-built fake `/proc`, `/sys`, `/var/lib/dpkg`...,
  and answers commands from a table.

In test-double terms (Meszaros, *xUnit Test Patterns*): a *dummy* is passed
but never used, a *stub* returns canned answers, a *fake* is a working but
simplified implementation, a *mock* verifies that expected calls happened,
and a *spy* records calls for later inspection. `FakeProbe` is a fake for
files (it really reads them, just from another root), a stub for commands,
and a spy (`probe.calls`).

Why not `unittest.mock.patch("builtins.open")`? Patching couples each test to
*how* the code reads (which function, which arguments), so harmless
refactors break tests. Injecting a probe couples tests only to the probe's
interface. And because `FakeProbe` shares the real file-reading code with
`HostProbe`, that code is exercised by every test.

### Scenarios as diffs

`tests/scenarios.py` describes each machine as a `{path: content}` dict.
`healthy()` is a working 24.04 desktop; every broken machine is
`healthy().but(...)` with only the differences, for example "kernel
6.8.0-47, DKMS built only for 6.8.0-45, headers missing". `test_scenarios.py`
runs all checks against all machines and compares against a table of
expected statuses, which doubles as documentation.

### The probe's error contract

* Missing file → `None`; missing directory → `[]`; missing command → `None`.
  These are normal answers.
* `PermissionError` propagates. The runner turns it into SKIP with "run with
  sudo".
* Inside a snap it is a `ConfinementError` (a `PermissionError` subclass),
  reported as "hidden by confinement" (see [snap.md](snap.md)).
* Any other exception in a check is a bug: the runner reports SKIP with
  `internal_error: true`, and the exit code becomes 3.

### Files before binaries

The checks read `/proc`, `/sys`, `/var/lib/dpkg/status` and `/var/lib/dkms`
instead of calling `lspci`, `dpkg-query`, `dkms status` or `mokutil`:

* Files are always there; binaries may not be installed (`pciutils` is not
  on every server).
* A strictly confined snap can read many files through interfaces but cannot
  execute host binaries.
* Files are trivially faked in tests; command output must be scripted.
* Output formats of tools change between releases; kernel interfaces such
  as `/proc/modules` are stable ABI.

Binaries are used only as fallbacks or for information that has no file
(`nvidia-smi` as the end-to-end test, `mokutil --test-key` for MOK
enrolment).

### Dependencies between checks

`Check.requires` lists checks that must PASS or WARN first. When there is no
GPU, ten checks are skipped with a one-line reason instead of producing ten
confusing failures. `--check X` pulls in X's dependencies automatically.

### Exit codes

0 pass, 1 warning, 2 failure, 3 tool error. argparse exits 2 on usage errors
by default; that is overridden to 3 so scripts can tell "your system has a
problem" from "you called the tool wrong". SKIP counts as success: "could not
or did not need to look" is not a fault in the system.

### JSON stability

`--json` carries a `schema_version`, documented by `docs/json-schema.json`.
Tests validate real output against the schema, so the documentation cannot
drift.

## Rules for checks

1. Read only through the probe.
2. Prefer files to commands; treat a missing command as normal.
3. Return exactly one `CheckResult` with your own id.
4. SKIP when the check does not apply; FAIL only when something is broken.
5. Every FAIL needs an `explanation`; give `fixes` whenever there is a
   concrete command, and make sure it is valid on 22.04 and 24.04.
6. Put what you looked at in `evidence`, and machine-friendly values in `facts`.
7. Add a scenario and a row in the scenario table.

## Known limitations

* `driver_package` assumes Ubuntu package names. On other distributions it
  still runs but the suggested commands may not apply.
* The CUDA table must be updated by hand when NVIDIA releases a new toolkit;
  unknown versions are reported as such rather than guessed.
* Inside a strict snap, five checks are skipped (see [snap.md](snap.md)).
* Multi-GPU systems with different NVIDIA driver requirements are reported
  as one driver installation.
