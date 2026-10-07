# The snap: strict confinement and what it means for the checks

## Strict vs classic confinement

A **strictly confined** snap runs in its own mount namespace, under an
AppArmor profile and a seccomp filter. It sees:

* its own files under `/snap/gpu-doctor/current`,
* the **base snap** (`core24`, an Ubuntu 24.04 userspace) as `/`,
* a fixed set of host directories bind-mounted on top: `/proc`, `/sys`,
  `/dev`, `/etc`, `/home`, `/run`, `/lib/modules`, `/usr/src`, `/var/log`,
  `/var/lib/snapd` and a few more (the list is in snapd's
  `cmd/snap-confine/mount-support.c`),
* the whole host root at `/var/lib/snapd/hostfs`, but AppArmor only allows
  reading the parts an *interface* grants.

Anything the AppArmor profile does not allow fails with `EACCES`, even for
root. Interfaces ("plugs") grant extra access; most hardware ones are not
connected automatically and need `snap connect` (or a store
auto-connection grant).

A **classic** snap has no confinement: it sees the host filesystem like a
deb would. Classic confinement needs manual approval by the Snap Store
reviewers and is reserved for tools that genuinely cannot work confined
(compilers, IDEs, some system tools). gpu-doctor was designed to work
*strictly* confined, accepting reduced coverage, rather than asking for
classic.

## Interfaces used

Verified against snapd's interface source (`interfaces/builtin/*.go` in
https://github.com/snapcore/snapd) and https://snapcraft.io/docs/supported-interfaces:

| Interface | Auto-connect | What gpu-doctor needs it for |
|---|---|---|
| `hardware-observe` | no | `/sys/{block,bus,class,devices,firmware}` (PCI devices for `gpu_present`, efivars for `secure_boot`), `/proc/modules`, `/etc/modprobe.d` |
| `kernel-module-observe` | no | `/sys/module` (module taint flags), `/proc/modules` |
| `system-observe` | no | the host's `os-release` via `/var/lib/snapd/hostfs/etc/os-release`; inside the snap `/etc/os-release` is a symlink that resolves into the base snap and would report "Ubuntu Core 24" |

```sh
sudo snap connect gpu-doctor:hardware-observe
sudo snap connect gpu-doctor:kernel-module-observe
sudo snap connect gpu-doctor:system-observe
```

Not used: `system-files` could expose `/var/lib/dpkg/status` and
`/var/lib/dkms`, but it needs a Snap Store review with a justification for
every path. That is the next step if the snap gets real users.

## What works where

| Check | deb | strict snap | Why |
|---|---|---|---|
| `system_info` | yes | yes | host os-release via hostfs |
| `gpu_present` | yes | yes | `/sys/bus/pci`; the snap ships its own `pci.ids` (stage-package) |
| `driver_package` | yes | skipped | host `/var/lib/dpkg/status` is not readable |
| `kernel_module` | yes | yes | `/proc/modules` |
| `module_build` | yes | skipped | needs dpkg and `/var/lib/dkms` |
| `kernel_headers` | yes | skipped | needs dpkg and DKMS state |
| `nouveau` | yes | yes | `/proc/modules`, `/etc/modprobe.d`, `/proc/cmdline` (not `/lib/modprobe.d`) |
| `secure_boot` | yes | partly | efivars yes; `mokutil` cannot be run |
| `version_mismatch` | yes | skipped | host `/usr/lib/<triplet>` is not readable |
| `nvidia_smi` | yes | skipped | host binaries cannot be executed |
| `cuda_compat` | yes | skipped | `/usr/local` is not readable |
| `container_toolkit` | yes | skipped | needs dpkg |
| `prime` | yes | yes | `/etc/prime-discrete` |

## How the code handles it

* `SystemProbe.path()` knows which directories are shared with the host. For
  any other path it reads the host's copy under `/var/lib/snapd/hostfs`, so a
  check can never silently inspect the base snap's dpkg database and report
  "no driver installed" on a machine that has one.
* Inside a snap every `PermissionError` is raised as `ConfinementError`. The
  runner turns that into a SKIP that says the file is hidden by confinement
  and suggests connecting the interfaces or installing the deb, instead of
  the misleading "run with sudo".
* `glob()` lists the fixed part of each pattern first, because `Path.glob`
  silently ignores unreadable directories and would make "not allowed to
  look" look like "nothing there".
* Checks that only use the package list as a *hint* (`kernel_module`,
  `nouveau`) treat "unknown" sensibly instead of skipping entirely.
* The `in_snap` test scenario lays the fake machine out exactly like this,
  with the AppArmor denials, so all of the above is tested without snapd.

## Building, testing, publishing

```sh
sudo snap install snapcraft --classic
sudo snap install lxd && sudo lxd init --auto
snapcraft pack                          # builds in a clean LXD container
sudo snap install --dangerous ./gpu-doctor_0.1.0_amd64.snap
sudo snap connect gpu-doctor:hardware-observe     # etc.
gpu-doctor --verbose
sudo journalctl -k | grep 'apparmor="DENIED"' | grep gpu-doctor   # see what was blocked
snappy-debug                            # (snap) suggests interfaces for denials
```

Publishing:

```sh
snapcraft login
snapcraft register gpu-doctor           # the name must be free; pick another if not
snapcraft upload --release=edge gpu-doctor_0.1.0_amd64.snap
# after testing from edge:
snapcraft release gpu-doctor <revision> stable
```

The first upload of a snap that plugs `hardware-observe` and friends may be
held for manual review; requesting auto-connection of those interfaces is a
separate request on https://forum.snapcraft.io in the "store-requests"
category.

## core22 vs core24

`core24` (Ubuntu 24.04, Python 3.12) is supported until 2034 and is what new
snaps should use. `core22` (22.04, Python 3.10) only makes sense to match an
existing 22.04 dependency. Because the snap carries its own Python, the base
does not limit which hosts it runs on: the core24 snap runs on 22.04 hosts too.
