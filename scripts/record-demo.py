#!/usr/bin/env python3
"""Record docs/demo.cast (asciicast v2) by really running gpu-doctor.

    python3 scripts/record-demo.py
    npx svg-term-cli --in docs/demo.cast --out docs/demo.svg --window --no-cursor

The demo runs against fake machines from the test suite (via --root), because
a recording should be reproducible on any computer. The command line in the
recording shows --root, so it is clear what is being diagnosed.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WIDTH, HEIGHT = 118, 40
PROMPT = "\033[1;32msneha@ubuntu\033[0m:\033[1;34m~\033[0m$ "

STEPS = [
    ("dkms_missing_after_kernel_upgrade", "after-kernel-upgrade", []),
    ("version_mismatch", "after-driver-upgrade", ["--check", "version_mismatch"]),
]


def run(root: Path, extra: list[str]) -> str:
    env = dict(os.environ, PYTHONPATH=str(ROOT / "src"), COLUMNS=str(WIDTH))
    proc = subprocess.run(
        [sys.executable, "-m", "gpudoctor", "--root", str(root), "--color", "always", *extra],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    return proc.stdout


def main() -> int:
    events: list[tuple[float, str]] = []
    t = 0.5

    def emit(text: str, delay: float) -> None:
        nonlocal t
        t += delay
        events.append((round(t, 3), text))

    with tempfile.TemporaryDirectory() as tmp:
        for scenario, label, extra in STEPS:
            shown_root = f"./demo/{label}"
            target = Path(tmp) / label
            subprocess.run(
                [sys.executable, str(ROOT / "scripts/make-demo-root.py"), scenario, str(target)],
                check=True,
                capture_output=True,
            )
            emit(PROMPT, 0.3)
            command = " ".join(["gpu-doctor", "--root", shown_root, *extra])
            for ch in command:
                emit(ch, 0.045)
            emit("\r\n", 0.6)
            output = run(target, extra).replace(str(target), shown_root)
            for line in output.splitlines():
                emit(line + "\r\n", 0.07)
            emit("", 2.5)
        emit(PROMPT, 0.2)
        emit("", 3.0)

    header = {
        "version": 2,
        "width": WIDTH,
        "height": HEIGHT,
        "env": {"SHELL": "/bin/bash", "TERM": "xterm-256color"},
    }
    out = ROOT / "docs" / "demo.cast"
    with out.open("w") as f:
        f.write(json.dumps(header) + "\n")
        for when, text in events:
            f.write(json.dumps([when, "o", text]) + "\n")
    print(f"wrote {out} ({len(events)} events, {t:.1f}s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
