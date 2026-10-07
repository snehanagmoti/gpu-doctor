import json

from gpudoctor.model import CheckResult, Evidence, Status, overall_status


def result(status: Status) -> CheckResult:
    return CheckResult(check_id="x", status=status, summary="s")


def test_status_serialises_as_plain_string():
    assert json.dumps(Status.WARN) == '"warn"'


def test_skip_is_not_a_problem():
    assert Status.SKIP.severity == Status.PASS.severity == 0
    assert Status.WARN.severity == 1
    assert Status.FAIL.severity == 2


def test_overall_status_picks_worst():
    assert overall_status([]) is Status.PASS
    assert overall_status([result(Status.PASS), result(Status.SKIP)]) is Status.PASS
    assert overall_status([result(Status.WARN), result(Status.PASS)]) is Status.WARN
    assert overall_status([result(Status.WARN), result(Status.FAIL)]) is Status.FAIL


def test_to_dict_is_json_ready():
    r = CheckResult(
        check_id="gpu_present",
        status=Status.PASS,
        summary="ok",
        fixes=("sudo true",),
        evidence=(Evidence("/proc/modules", "nvidia 1 0"),),
        facts={"k": "v"},
    )
    data = json.loads(json.dumps(r.to_dict()))
    assert data == {
        "id": "gpu_present",
        "status": "pass",
        "summary": "ok",
        "explanation": "",
        "fixes": ["sudo true"],
        "evidence": [{"source": "/proc/modules", "value": "nvidia 1 0"}],
        "facts": {"k": "v"},
        "internal_error": False,
    }
