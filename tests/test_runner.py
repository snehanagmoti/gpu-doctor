import pytest

from gpudoctor.model import CheckResult, Status
from gpudoctor.probe import FakeProbe
from gpudoctor.runner import Check, UnknownCheckError, run_checks, select_checks


def make(check_id, status=Status.PASS, requires=(), exc=None):
    def func(probe):
        if exc is not None:
            raise exc
        return CheckResult(check_id=check_id, status=status, summary=f"{check_id} ran")

    return Check(id=check_id, title=check_id.upper(), func=func, requires=requires)


@pytest.fixture
def probe(tmp_path):
    return FakeProbe(tmp_path)


def test_runs_in_order(probe):
    results = run_checks([make("a"), make("b", Status.WARN)], probe)
    assert [(r.check_id, r.status) for r in results] == [("a", Status.PASS), ("b", Status.WARN)]


def test_dependency_failure_skips_dependants(probe):
    checks = [make("gpu", Status.FAIL), make("module", requires=("gpu",)), make("info")]
    results = run_checks(checks, probe)
    assert results[1].status is Status.SKIP
    assert "GPU" in results[1].summary  # names the dependency by title
    assert results[2].status is Status.PASS  # unrelated checks still run


def test_warn_satisfies_dependency(probe):
    results = run_checks([make("a", Status.WARN), make("b", requires=("a",))], probe)
    assert results[1].status is Status.PASS


def test_skip_propagates(probe):
    checks = [make("a", Status.SKIP), make("b", requires=("a",)), make("c", requires=("b",))]
    assert [r.status for r in run_checks(checks, probe)] == [Status.SKIP] * 3


def test_exception_becomes_skip_with_internal_error(probe):
    [result] = run_checks([make("boom", exc=ZeroDivisionError("division by zero"))], probe)
    assert result.status is Status.SKIP
    assert result.internal_error
    assert "ZeroDivisionError" in result.summary
    assert result.evidence and result.evidence[0].source == "traceback"


def test_permission_error_suggests_sudo(probe):
    err = PermissionError(13, "Permission denied", "/sys/firmware/efi/efivars/x")
    [result] = run_checks([make("p", exc=err)], probe)
    assert result.status is Status.SKIP
    assert not result.internal_error
    assert "/sys/firmware/efi/efivars/x" in result.summary
    assert result.fixes == ("sudo gpu-doctor",)


def test_wrong_check_id_is_internal_error(probe):
    bad = Check(id="a", title="A", func=lambda p: CheckResult("zzz", Status.PASS, "x"))
    [result] = run_checks([bad], probe)
    assert result.internal_error and result.check_id == "a"


def test_select_checks_adds_dependencies_in_order():
    checks = [
        make("info"),
        make("gpu"),
        make("pkg", requires=("gpu",)),
        make("mod", requires=("pkg",)),
    ]
    assert [c.id for c in select_checks(checks, ["mod"])] == ["gpu", "pkg", "mod"]
    assert [c.id for c in select_checks(checks, None)] == ["info", "gpu", "pkg", "mod"]
    with pytest.raises(UnknownCheckError):
        select_checks(checks, ["nope"])
