# Contributing to gpu-doctor

Thanks for helping! Bug reports from real machines are the most valuable
contribution: they become new test scenarios.

## Reporting a bug

Open an issue and paste the output of:

```sh
gpu-doctor --report
```

It redacts your hostname, username, home directory, UUIDs, serial numbers and
MAC addresses. Please also say what you expected gpu-doctor to tell you.

## Development setup

```sh
git clone https://github.com/snehanagmoti/gpu-doctor.git
cd gpu-doctor
python3 -m venv .venv && . .venv/bin/activate
pip install -e . pytest pytest-cov ruff mypy
pytest --cov
```

No NVIDIA GPU is needed: every check is tested against fake machines.

## Adding or changing a check

1. Read [docs/design.md](docs/design.md), especially "Rules for checks".
2. Write the check in `src/gpudoctor/checks/<id>.py`: a `run(probe)` function
   returning a `CheckResult`, and a `CHECK = Check(...)` constant.
3. Add it to `ALL_CHECKS` in `src/gpudoctor/checks/__init__.py`, after the
   checks it depends on.
4. Describe the real-world situation as a scenario in `tests/scenarios.py`,
   written as a diff against `healthy()`, and add a row to the table in
   `tests/test_scenarios.py`.
5. Add the check to the README table and the man page (`docs/gpu-doctor.1`);
   `tests/test_docs_consistency.py` fails until you do.
6. If you are not sure a suggested command is right on both 22.04 and 24.04,
   say so in the pull request.

## Before you open a pull request

```sh
ruff check . && ruff format --check .
mypy
pytest --cov
./scripts/build-deb.sh      # optional: builds and lints the Debian package
```

CI runs all of this on Ubuntu 22.04 and 24.04, builds the snap, and installs
the `.deb` in clean LXD containers.

## Commits

* One logical change per commit, with tests in the same commit.
* Subject line in the imperative, under about 70 characters
  ("Add PRIME check", not "added prime stuff").
* A body that says *why*, especially for anything learned the hard way.

## Releases

1. Update `__version__` in `src/gpudoctor/__init__.py`, `version` in
   `snap/snapcraft.yaml`, `CHANGELOG.md`, the man page header and
   `debian/changelog` (`dch -v X.Y.Z-1`).
2. Commit and push, wait for CI to pass, then publish a release on GitHub
   (Releases → Draft a new release, new tag `vX.Y.Z` on `main`, notes from
   CHANGELOG.md). The release workflow builds the `.deb`, snap and wheel and
   attaches them to it.
3. Upload to the PPA (`./scripts/ppa-upload.sh 1 jammy noble`) and the Snap
   Store (`snapcraft upload --release=edge ...`).

## Code of conduct

This project follows the [Code of Conduct](CODE_OF_CONDUCT.md).
