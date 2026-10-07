# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
The JSON output has its own `schema_version`, see [docs/json-output.md](docs/json-output.md).

## [Unreleased]

## [0.1.0] - 2026-10-07

### Added

- Thirteen read-only checks: system information, NVIDIA GPU present, driver
  package, kernel module loaded, module built for the running kernel
  (prebuilt or DKMS), kernel headers, nouveau conflict, Secure Boot and MOK
  enrolment, module/library version mismatch, nvidia-smi, CUDA toolkit
  compatibility, Docker GPU support and hybrid graphics (PRIME).
- Coloured text output that honours `NO_COLOR`, `--verbose` evidence,
  `--json` with a documented schema, and a redacted `--report`.
- Exit codes 0 (ok), 1 (warnings), 2 (failures), 3 (tool error).
- Man page and bash completion.
- Debian packaging with autopkgtests, PPA upload scripts for 22.04 and 24.04.
- Strictly confined snap (core24).
- GitHub Actions CI and LXD install tests.

[Unreleased]: https://github.com/snehanagmoti/gpu-doctor/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/snehanagmoti/gpu-doctor/releases/tag/v0.1.0
