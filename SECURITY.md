# Security policy

gpu-doctor is read-only: it never changes the system and never runs the
commands it suggests. It does read some root-only files when run with
`sudo`, and it runs a handful of read-only programs (`nvidia-smi`,
`mokutil`, `modinfo`, `nvcc`, `prime-select`, `lspci`) found on `PATH`.

If you find a way to make gpu-doctor change the system, run an unexpected
program, or leak information that `--report` should have redacted, please
do not open a public issue. Use GitHub's private vulnerability reporting
(Security tab, "Report a vulnerability") or e-mail
snehanagmoti2004@gmail.com.

Only the latest release is supported.
