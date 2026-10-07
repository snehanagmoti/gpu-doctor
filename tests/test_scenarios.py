"""End-to-end: every check against every fake machine.

Each row is one real-world situation and the status we expect from each
check, in registry order. Reading a row tells the story of that machine:
for example, after a kernel upgrade without headers, the module is not
loaded *because* DKMS did not build it *because* the headers are missing.
"""

import pytest

from gpudoctor.checks import ALL_CHECKS
from gpudoctor.render import exit_code
from gpudoctor.runner import run_checks

import scenarios

# Column order = ALL_CHECKS order:
# system_info gpu_present driver_package kernel_module module_build
# kernel_headers nouveau secure_boot version_mismatch nvidia_smi
# cuda_compat container_toolkit prime
P, W, F, S = "pass", "warn", "fail", "skip"

# fmt: off
EXPECTED = {
    "healthy":                           ([P, P, P, P, P, S, P, P, P, P, P, S, S], 0),
    "healthy_dkms":                      ([P, P, P, P, P, P, P, P, P, P, P, S, S], 0),
    "no_gpu":                            ([P, F, S, S, S, S, S, S, S, S, S, S, S], 2),
    "no_driver":                         ([P, P, F, S, S, S, P, P, S, S, S, S, S], 2),
    "nouveau_loaded":                    ([P, P, P, F, P, S, F, P, S, F, P, S, S], 2),
    "dkms_missing_after_kernel_upgrade": ([P, P, P, F, F, F, P, P, S, F, P, S, S], 2),
    "secure_boot_unsigned":              ([P, P, P, F, P, P, P, F, S, F, P, S, S], 2),
    "version_mismatch":                  ([P, P, P, P, P, S, P, P, F, F, P, S, S], 2),
    "run_installer":                     ([P, P, W, P, P, S, P, P, P, P, P, S, S], 1),
    "in_docker":                         ([P, P, S, P, S, S, P, S, P, P, P, S, S], 0),
    "prebuilt_missing_for_new_kernel":   ([P, P, P, F, F, S, P, P, S, F, P, S, S], 2),
    "multiple_branches":                 ([P, P, W, P, P, S, P, P, W, P, P, S, S], 1),
    "old_driver_new_cuda":               ([P, P, P, P, P, S, P, P, P, P, F, S, S], 2),
    "hybrid_integrated_only":            ([P, P, P, P, P, S, P, P, P, P, P, S, W], 1),
    "docker_without_toolkit":            ([P, P, P, P, P, S, P, P, P, P, P, W, S], 1),
    "legacy_bios":                       ([P, P, P, P, P, S, P, S, P, P, P, S, S], 0),
    "in_snap":                           ([P, P, S, P, S, S, P, P, S, S, S, S, S], 0),
}
# fmt: on


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_scenario(name, tmp_path):
    expected_statuses, expected_exit = EXPECTED[name]
    probe = getattr(scenarios, name)().probe(tmp_path)
    results = run_checks(ALL_CHECKS, probe)
    actual = {r.check_id: r.status.value for r in results}
    expected = dict(zip([c.id for c in ALL_CHECKS], expected_statuses, strict=True))
    assert actual == expected
    assert exit_code(results) == expected_exit
    assert not any(r.internal_error for r in results)
    # Every non-passing result must tell the user something.
    for r in results:
        assert r.summary
        if r.status.value == "fail":
            assert r.explanation, r.check_id


def test_every_scenario_is_covered():
    defined = {
        name
        for name in dir(scenarios)
        if callable(getattr(scenarios, name))
        and getattr(getattr(scenarios, name), "__module__", "") == "scenarios"
        and getattr(scenarios, name).__annotations__.get("return") == "Scenario"
    }
    assert defined == set(EXPECTED)
