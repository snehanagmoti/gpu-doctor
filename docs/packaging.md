# Debian packaging and the PPA

This document explains every file in `debian/`, how to build and check the
package, how PPA uploads are versioned, and every lintian finding the package
hit on the way to a clean result.

Authoritative references (check them when something here looks out of date):

* Debian Policy: https://www.debian.org/doc/debian-policy/
* Debian New Maintainers' Guide / Guide for Debian Maintainers:
  https://www.debian.org/doc/manuals/debmake-doc/
* dh-python / pybuild: `man pybuild`, https://wiki.debian.org/Python/Pybuild
* Ubuntu Packaging Guide: https://canonical-ubuntu-packaging-guide.readthedocs-hosted.com/
* Launchpad PPA help: https://help.launchpad.net/Packaging/PPA

## The files

| File | Purpose |
|---|---|
| `debian/control` | Source package (build dependencies, Standards-Version, VCS links) and the binary package `gpu-doctor` (dependencies, description). |
| `debian/rules` | The build recipe: a makefile whose only rule hands everything to `dh` with the `pybuild` build system. |
| `debian/changelog` | Version history in the strict format `dpkg-parsechangelog` reads. The top entry decides the version and target series. |
| `debian/copyright` | DEP-5 machine-readable copyright file: who owns what, under which licence. |
| `debian/source/format` | `3.0 (quilt)`: the source package is an upstream tarball plus a separate `debian/` tarball. |
| `debian/gpu-doctor.manpages` | `dh_installman` installs `docs/gpu-doctor.1` to `/usr/share/man/man1/`. |
| `debian/gpu-doctor.install` | `dh_install` copies the bash completion to `/usr/share/bash-completion/completions/`. |
| `debian/gpu-doctor.docs` | `dh_installdocs` copies the README and the JSON schema to `/usr/share/doc/gpu-doctor/`. |
| `debian/gpu-doctor.lintian-overrides` | One justified override (see below). |
| `debian/tests/` | autopkgtest: tests run against the *installed* package. |
| `debian/watch` | Tells `uscan` where new upstream releases (GitHub tags) appear. |
| `debian/upstream/metadata` | DEP-12 metadata: bug tracker and repository URLs. |

### debian/control decisions

* `debhelper-compat (= 13)` selects debhelper compatibility level 13 (the
  current recommended level, available on both jammy and noble) without a
  separate `debian/compat` file.
* `dh-sequence-python3` turns on the `dh_python3` step, which rewrites the
  `#!` line, computes `${python3:Depends}` and byte-compiles on install. It
  replaces the older `dh $@ --with python3`.
* `python3-pytest <!nocheck>`: the build profile annotation means the
  dependency is only needed when the tests run, so
  `DEB_BUILD_OPTIONS=nocheck` builds work without it.
* `Architecture: all`: pure Python, one `.deb` for every architecture.
* `Rules-Requires-Root: no`: the build never needs (fake)root.
* Only `Suggests` for the optional helper programs (`mokutil`, `pciutils`,
  `nvidia-prime`, `ubuntu-drivers-common`): every check works without them.

### debian/rules, line by line

```make
export PYBUILD_NAME = gpudoctor
```
The name of the Python module; pybuild uses it in paths and messages.

```make
export PYBUILD_BEFORE_TEST = cp -r {dir}/tests {dir}/docs {dir}/completions {dir}/README.md {build_dir}
export PYBUILD_TEST_ARGS = -p no:cacheprovider tests
export PYBUILD_AFTER_TEST = rm -rf {build_dir}/tests ...
```
pybuild runs the tests inside `.pybuild/cpython3_3.X_gpudoctor/build`, which
contains only the *built* package, so the tests really exercise what will be
installed. The tests also read `docs/`, `completions/` and `README.md`
(consistency tests), so those are copied in and removed again so they are not
installed. `-p no:cacheprovider` stops pytest writing `.pytest_cache` into the
build tree.

```make
%:
	dh $@ --buildsystem=pybuild
```
Every target (`clean`, `build`, `binary`, ...) is handled by `dh`, which runs
the debhelper commands in order: `dh_auto_build` → `setup.py build` via
pybuild for each supported Python, `dh_auto_test` → pytest,
`dh_auto_install` → install into `debian/gpu-doctor/`, then `dh_installdocs`,
`dh_installman`, `dh_install`, `dh_python3`, `dh_gencontrol`, `dh_builddeb`.

### Why 3.0 (quilt) and not 3.0 (native)?

A *native* package has no separate upstream tarball and no Debian revision
(`0.1.0`, not `0.1.0-1`). That fits software that exists only as a Debian
package. gpu-doctor is an upstream project (GitHub releases, pip, snap) that
*also* has packaging, so:

* the upstream tarball is the release, and the packaging is a separate layer;
* the packaging can be fixed (`0.1.0-2`) without a new upstream release;
* PPA rebuilds need a Debian revision to attach `~ppa1~22.04` to.

`scripts/build-deb.sh` creates `gpu-doctor_<version>.orig.tar.gz` with
`git archive`, excluding `debian/`. `debian/watch` describes the same tarball
on GitHub so `uscan` can fetch it.

### Why setup.py/setup.cfg and the distutils pybuild plugin?

Ubuntu 22.04 ships setuptools 59.6, which cannot read PEP 621 metadata from
`pyproject.toml` (that needs setuptools 61). Metadata therefore lives in
`setup.cfg`, which every setuptools version reads, with a two-line `setup.py`
shim. The project was test-built with setuptools 59.6.0 on Python 3.10.

lintian reports one *informational* tag about this:
`missing-prerequisite-for-pyproject-backend`. It suggests building through
pybuild's PEP 517 plugin (`pybuild-plugin-pyproject`). That is the better
long-term direction, and the switch is easy once jammy support is dropped;
for now the classic plugin builds identically on both releases.

## Testing on both releases

The package is built and linted on 22.04 and 24.04 in CI. To reproduce the
22.04 build locally on a 24.04 machine, use a chroot:

```sh
sudo debootstrap --variant=buildd --components=main,universe jammy /srv/jammy http://archive.ubuntu.com/ubuntu
sudo chroot /srv/jammy apt-get install -y debhelper dh-python python3-all \
    python3-setuptools python3-pytest devscripts lintian fakeroot git
sudo git clone . /srv/jammy/root/src
sudo chroot /srv/jammy sh -c 'cd /root/src && ./scripts/build-deb.sh /root/build-area'
```

This found two problems that only show up on 22.04: the lintian override
above, and pytest 6.2 not knowing the `pythonpath` ini option (now handled in
`tests/conftest.py`).

## Building and checking

```sh
sudo apt install debhelper dh-python python3-all python3-setuptools \
    python3-pytest lintian devscripts autopkgtest
./scripts/build-deb.sh                 # ../build-area/gpu-doctor_0.1.0-1_all.deb
sudo apt install ../build-area/gpu-doctor_0.1.0-1_all.deb
```

`build-deb.sh` ends with
`lintian --info --display-info --pedantic --fail-on error,warning`, so the
build fails on any lintian error or warning.

For a build in a clean chroot, as Launchpad does it, use sbuild:

```sh
sudo apt install sbuild mmdebstrap
mmdebstrap --variant=buildd noble ~/.cache/sbuild/noble-amd64.tar.zst
sbuild -d noble ../build-area/gpu-doctor_0.1.0-1.dsc
```

### autopkgtest

`debian/tests/control` defines two tests that run against the installed
package:

* `smoke` (superficial): `--version`, `--list-checks`, valid `--json`, and
  exit status 3 for a usage error.
* `unit`: the full pytest suite against `/usr/lib/python3/dist-packages`,
  for every supported Python (`py3versions -s`).

Run them in a throwaway LXD container:

```sh
autopkgtest-build-lxd ubuntu-daily:noble     # once
autopkgtest ../build-area/gpu-doctor_0.1.0-1_all.deb . -- lxd autopkgtest/ubuntu/noble/amd64
```

## lintian findings and what they taught

| Tag | Why it appeared | Fix |
|---|---|---|
| `unnecessary-testsuite-autopkgtest-field` | `Testsuite: autopkgtest` in `debian/control` is added automatically by `dpkg-source` when `debian/tests/control` exists. | Removed the field. |
| `runtime-test-file-uses-supported-python-versions-without-test-depends` | `debian/tests/unit` loops over `py3versions -s`, but without `python3-all` only the default Python is installed, so other versions would be silently untested. | Added `python3-all` to the test's `Depends`. |
| dpkg-source: *Version number suggests Ubuntu changes, but Maintainer: does not have Ubuntu address* | The first version was `0.1.0-0ubuntu1`. A version containing `ubuntu` means "changed by Ubuntu developers", which this package is not. | Use the plain Debian revision `0.1.0-1`. |
| `binary-nmu-debian-revision-in-source` | The first PPA scheme, `~ppa1~22.04.1`, put two dots in the revision, which is the shape of a binary-only NMU (`1.1.1`). | PPA versions are `0.1.0-1~ppa1~22.04`. |
| `initial-upload-closes-no-bugs` | A Debian package's first changelog entry should close its ITP bug. | Overridden with a comment: the package is not in Debian. File an ITP before proposing it. |
| `mismatched-override` (jammy only) | The override first named a file (`[usr/share/doc/...]`). noble's lintian reports the tag with that context, jammy's without, so on jammy the override did not match and the tag fired anyway. Found by building in a 22.04 chroot. | The override names only the tag, which matches with or without context. |
| `missing-prerequisite-for-pyproject-backend` (info) | See "Why setup.py" above. | Kept deliberately for jammy support. |
| `out-of-date-standards-version` (info, noble) | `Standards-Version: 4.6.0`. noble's lintian knows 4.6.2, but jammy's lintian only knows up to 4.6.0 and reports a newer value as the *warning* `newer-standards-version`. | Kept at 4.6.0, the newest version both releases' lintian understand; nothing in 4.6.1/4.6.2 affects this package. |

## PPA uploads

### Versions

| Upload | Version | Why |
|---|---|---|
| packaging in git | `0.1.0-1` | upstream 0.1.0, first packaging revision |
| PPA, 22.04 | `0.1.0-1~ppa1~22.04` | |
| PPA, 24.04 | `0.1.0-1~ppa1~24.04` | must differ from the jammy upload: one PPA cannot hold the same version twice |
| PPA rebuild | `0.1.0-1~ppa2~24.04` | a packaging-only fix to a PPA upload |

`~` sorts *before* everything in Debian version comparison, so
`0.1.0-1~ppa1~24.04 < 0.1.0-1`: if the package ever reaches the Ubuntu
archive, the archive version wins automatically. And
`~22.04 < ~24.04`, so upgrading the machine from 22.04 to 24.04 upgrades the
package. Check any pair with `dpkg --compare-versions A lt B && echo yes`.

### One-time Launchpad setup

1. Create an account at https://launchpad.net and set a username (here
   `snehanagmoti`).
2. Create a GPG key: `gpg --full-generate-key` (RSA 4096 or ed25519), using
   the same name and e-mail as in `debian/changelog`.
3. Publish it: `gpg --keyserver keyserver.ubuntu.com --send-keys <FINGERPRINT>`.
4. Add the fingerprint at https://launchpad.net/~/+editpgpkeys. Launchpad
   e-mails an encrypted message; decrypt it with `gpg -d` and open the link.
5. Create the PPA at https://launchpad.net/~/+activate-ppa with the name
   `gpu-doctor`. (If Launchpad asks you to sign the Ubuntu Code of Conduct
   first, do that from your profile page.)
6. `sudo apt install dput`. Ubuntu's default `dput` configuration already
   understands targets of the form `ppa:<user>/<ppa>`.

### Uploading

```sh
export DEBEMAIL=snehanagmoti2004@gmail.com DEBFULLNAME="Sneha Nagmoti"
./scripts/ppa-upload.sh 1 jammy noble
```

For each series the script builds a *signed source-only* package
(`dpkg-buildpackage -S`), includes the orig tarball on the first upload
(`-sa`), and runs `dput ppa:snehanagmoti/gpu-doctor <file>_source.changes`.
Launchpad e-mails an "Accepted" or "Rejected" message within minutes and then
builds the `.deb` on its own builders (jammy builds use Python 3.10 and
setuptools 59; noble builds use 3.12 and 68). Watch the build logs at
https://launchpad.net/~snehanagmoti/+archive/ubuntu/gpu-doctor/+packages.

Launchpad rejects an upload whose orig tarball differs from one it already
has for the same version. `build-deb.sh` therefore reuses an existing
`.orig.tar.gz` in the output directory instead of regenerating it.

## Getting into the Ubuntu archive

A PPA is a personal archive. To reach `apt install gpu-doctor` for everyone,
the usual route is through Debian, since Ubuntu syncs most of its universe
component from Debian automatically:

1. File an ITP bug against `wnpp` in Debian, then close it from the first
   changelog entry (and remove the lintian override).
2. Find a sponsor: the Debian Python Team (packaging under
   `salsa.debian.org/python-team/packages/`) or mentors.debian.net.
3. After the package is accepted into Debian unstable, it is synced into the
   next Ubuntu development release. Getting it into an existing LTS would
   additionally need the backports process.

Packaging directly for Ubuntu (a new package in universe sponsored by an
Ubuntu core developer, reviewed by the Archive Admins) is possible but Debian
first is the recommended path.
