import json
import subprocess
import sys
from pathlib import Path

import pytest

from gpudoctor import __version__, cli
from gpudoctor.checks import ALL_CHECKS
from gpudoctor.model import CheckResult, Status
from gpudoctor.render import render_text, use_colour
from gpudoctor.runner import Check

from scenarios import healthy, no_gpu, nouveau_loaded

SCHEMA = Path(__file__).resolve().parent.parent / "docs" / "json-schema.json"


def run_cli(capsys, *args):
    try:
        code = cli.main(list(args))
    except SystemExit as exc:  # argparse exits directly for usage errors
        code = exc.code
    out, err = capsys.readouterr()
    return code, out, err


@pytest.fixture
def healthy_root(tmp_path):
    healthy().probe(tmp_path)
    return str(tmp_path)


def test_list_checks(capsys):
    code, out, _ = run_cli(capsys, "--list-checks")
    assert code == 0
    ids = [line.split()[0] for line in out.splitlines()]
    assert ids == [c.id for c in ALL_CHECKS]


def test_version(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["--version"])
    assert exc.value.code == 0
    assert capsys.readouterr().out.strip() == f"gpu-doctor {__version__}"


def test_usage_errors_exit_3_not_2(capsys):
    code, _, err = run_cli(capsys, "--check", "no_such_check")
    assert code == 3
    assert "unknown check id" in err
    with pytest.raises(SystemExit) as exc:
        cli.main(["--frobnicate"])
    assert exc.value.code == 3
    with pytest.raises(SystemExit) as exc:
        cli.main(["--json", "--report"])  # mutually exclusive
    assert exc.value.code == 3


def test_bad_root(capsys, tmp_path):
    code, _, err = run_cli(capsys, "--root", str(tmp_path / "missing"))
    assert code == 3
    assert "is not a directory" in err


def test_text_output_healthy(capsys, healthy_root):
    code, out, _ = run_cli(capsys, "--root", healthy_root, "--color", "never")
    assert code == 0
    assert "PASS  NVIDIA GPU present" in out
    # --root never runs this machine's binaries.
    assert "Commands are not run when inspecting another root" in out
    assert out.rstrip().endswith("Nothing on this system was changed.")
    assert "\033[" not in out


def test_failures_show_fixes_and_exit_2(capsys, tmp_path):
    nouveau_loaded().probe(tmp_path)
    code, out, _ = run_cli(capsys, "--root", str(tmp_path), "--color", "never")
    assert code == 2
    assert "Suggested commands (review before running):" in out
    assert "$ sudo update-initramfs -u" in out


def test_verbose_shows_evidence_and_ids(capsys, healthy_root):
    _, out, _ = run_cli(capsys, "--root", healthy_root, "--verbose", "--color", "never")
    assert "id: gpu_present" in out
    assert "· /proc/modules: nvidia, nvidia_modeset, nvidia_drm, nvidia_uvm" in out


def test_check_selection_includes_dependencies(capsys, healthy_root):
    code, out, _ = run_cli(capsys, "--root", healthy_root, "--json", "-c", "version_mismatch")
    ids = [c["id"] for c in json.loads(out)["checks"]]
    assert ids == ["gpu_present", "kernel_module", "version_mismatch"]
    assert code == 0
    _, out, _ = run_cli(capsys, "--root", healthy_root, "--json", "-c", "nouveau,system_info")
    assert [c["id"] for c in json.loads(out)["checks"]] == ["system_info", "gpu_present", "nouveau"]


def _validate(instance, schema, root=None, path="$"):
    """A tiny JSON Schema subset validator (keeps the test dependency-free)."""
    root = root or schema
    if "$ref" in schema:
        schema = root["$defs"][schema["$ref"].split("/")[-1]]
    if "const" in schema:
        assert instance == schema["const"], path
    if "enum" in schema:
        assert instance in schema["enum"], path
    kind = schema.get("type")
    types = {"object": dict, "array": list, "string": str, "integer": int, "boolean": bool}
    if kind:
        assert isinstance(instance, types[kind]), f"{path}: expected {kind}"
    if kind == "object":
        for key in schema.get("required", []):
            assert key in instance, f"{path}: missing {key}"
        props = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            assert set(instance) <= set(props), f"{path}: extra keys {set(instance) - set(props)}"
        for key, value in instance.items():
            sub = props.get(key, schema.get("additionalProperties"))
            if isinstance(sub, dict):
                _validate(value, sub, root, f"{path}.{key}")
    if kind == "array":
        for i, item in enumerate(instance):
            _validate(item, schema["items"], root, f"{path}[{i}]")
    if kind == "string" and "minLength" in schema:
        assert len(instance) >= schema["minLength"], path


@pytest.mark.parametrize("scenario", [healthy, no_gpu, nouveau_loaded])
def test_json_matches_documented_schema(capsys, tmp_path, scenario):
    scenario().probe(tmp_path)
    code, out, _ = run_cli(capsys, "--root", str(tmp_path), "--json")
    document = json.loads(out)
    _validate(document, json.loads(SCHEMA.read_text()))
    assert document["exit_code"] == code


def test_report_is_redacted(capsys, tmp_path, monkeypatch):
    healthy().but(files={"/etc/hostname-note": ""}).probe(tmp_path)
    monkeypatch.setenv("USER", "sneha")
    monkeypatch.setenv("HOME", "/home/sneha")
    monkeypatch.delenv("SUDO_USER", raising=False)
    code, out, _ = run_cli(capsys, "--root", str(tmp_path), "--report")
    assert code == 0
    assert out.startswith(f"### gpu-doctor {__version__} report (exit status 0)")
    assert "sneha-desktop" not in out  # hostname from /proc/sys/kernel/hostname
    assert "[PASS] NVIDIA GPU present" in out


def test_colour_rules():
    class Tty:
        def isatty(self):
            return True

    class Pipe:
        def isatty(self):
            return False

    assert use_colour("auto", Tty(), {}) is True
    assert use_colour("auto", Tty(), {"NO_COLOR": "1"}) is False
    assert use_colour("auto", Tty(), {"NO_COLOR": ""}) is True  # empty means unset
    assert use_colour("auto", Tty(), {"TERM": "dumb"}) is False
    assert use_colour("auto", Pipe(), {}) is False
    assert use_colour("always", Pipe(), {"NO_COLOR": "1"}) is True
    assert use_colour("never", Tty(), {}) is False


def test_colour_output():
    result = CheckResult("x", Status.FAIL, "broken", explanation="why", fixes=("sudo true",))
    out = render_text([result], {"x": "X"}, colour=True, width=80)
    assert "\033[31mFAIL\033[0m" in out


def test_internal_error_exits_3(capsys, healthy_root, monkeypatch):
    def boom(probe):
        raise RuntimeError("bug")

    broken = (*ALL_CHECKS[:1], Check(id="gpu_present", title="GPU", func=boom))
    monkeypatch.setattr(cli, "ALL_CHECKS", broken)
    code, out, _ = run_cli(capsys, "--root", healthy_root, "--color", "never")
    assert code == 3
    assert "Internal error in this check: RuntimeError: bug" in out
    assert "This is a bug in gpu-doctor" in out


def test_unexpected_renderer_error_exits_3(capsys, healthy_root, monkeypatch):
    def broken_render(*args, **kwargs):
        raise ValueError("render bug")

    monkeypatch.setattr(cli, "render_text", broken_render)
    code, _, err = run_cli(capsys, "--root", healthy_root)
    assert code == 3
    assert "internal error: ValueError: render bug" in err


def test_python_dash_m(tmp_path):
    # Wherever gpudoctor was imported from: src/ in a checkout, the build
    # directory during the Debian build, dist-packages under autopkgtest.
    import gpudoctor

    src = Path(gpudoctor.__file__).resolve().parent.parent
    proc = subprocess.run(
        [sys.executable, "-m", "gpudoctor", "--version"],
        capture_output=True,
        text=True,
        env={"PYTHONPATH": str(src), "PATH": "/usr/bin:/bin"},
        check=False,
    )
    assert proc.returncode == 0
    assert proc.stdout.strip() == f"gpu-doctor {__version__}"
