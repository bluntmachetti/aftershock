"""Tests for aftershock.stats — hand-verified values for every routine.

These guard the Tier-0 measurement math: a wrong p-value or power curve would
make every later "improvement" claim untrustworthy, which is the whole point of
building the harness first.
"""

from __future__ import annotations

import math

import pytest

from aftershock.stats import (
    bootstrap_ci,
    mean,
    norm_cdf,
    norm_ppf,
    power_for_n,
    required_n_for_effect,
    sample_sd,
    sign_test_p,
    variance_components,
)

# ---------------------------------------------------------------------------
# Descriptive
# ---------------------------------------------------------------------------


def test_mean_and_sd_match_bench() -> None:
    xs = [10.0, 20.0]
    assert math.isclose(mean(xs), 15.0)
    # sample sd ddof=1: sqrt(((10-15)^2 + (20-15)^2)/1) = sqrt(50)
    assert math.isclose(sample_sd(xs), math.sqrt(50.0))


def test_sd_single_value_is_zero() -> None:
    assert sample_sd([7.0]) == 0.0
    assert mean([]) == 0.0


# ---------------------------------------------------------------------------
# Normal distribution
# ---------------------------------------------------------------------------


def test_norm_cdf_known_points() -> None:
    assert math.isclose(norm_cdf(0.0), 0.5, abs_tol=1e-12)
    assert math.isclose(norm_cdf(1.959963985), 0.975, abs_tol=1e-6)


def test_norm_ppf_inverts_cdf() -> None:
    # Canonical z-values.
    assert math.isclose(norm_ppf(0.975), 1.959963985, abs_tol=1e-6)
    assert math.isclose(norm_ppf(0.8), 0.8416212336, abs_tol=1e-6)
    # Round-trip across the range.
    for p in (0.001, 0.05, 0.3, 0.5, 0.7, 0.95, 0.999):
        assert math.isclose(norm_cdf(norm_ppf(p)), p, abs_tol=1e-9)


def test_norm_ppf_rejects_out_of_range() -> None:
    with pytest.raises(ValueError):
        norm_ppf(0.0)
    with pytest.raises(ValueError):
        norm_ppf(1.0)


# ---------------------------------------------------------------------------
# Sign test
# ---------------------------------------------------------------------------


def test_sign_test_all_positive_n5() -> None:
    # 5 positive diffs: k=0, tail = C(5,0)*0.5^5 = 1/32; p = 2/32 = 0.0625
    assert math.isclose(sign_test_p([1, 2, 3, 4, 5]), 0.0625)


def test_sign_test_mixed() -> None:
    # pos=3, neg=1, n=4, k=1, tail=(1+4)/16=0.3125, p=0.625
    assert math.isclose(sign_test_p([1, 2, 3, -1]), 0.625)


def test_sign_test_ties_dropped() -> None:
    # zeros excluded entirely; remaining all positive -> same as n=2 all-positive
    # n=2, k=0, tail=C(2,0)*0.25=0.25, p=0.5
    assert math.isclose(sign_test_p([0, 0, 1, 2]), 0.5)


def test_sign_test_no_nonzero_is_one() -> None:
    assert sign_test_p([0, 0, 0]) == 1.0
    assert sign_test_p([]) == 1.0


# ---------------------------------------------------------------------------
# Bootstrap CI (deterministic)
# ---------------------------------------------------------------------------


def test_bootstrap_ci_is_deterministic() -> None:
    diffs = [3.0, 5.0, 7.0, 9.0, 11.0]
    a = bootstrap_ci(diffs, rng_seed=42)
    b = bootstrap_ci(diffs, rng_seed=42)
    assert a == b
    # Interval brackets the sample mean (7.0)
    assert a.lower <= 7.0 <= a.upper


def test_bootstrap_ci_single_value() -> None:
    ci = bootstrap_ci([4.0])
    assert ci.lower == 4.0 and ci.upper == 4.0


def test_bootstrap_ci_empty() -> None:
    ci = bootstrap_ci([])
    assert ci.lower == 0.0 and ci.upper == 0.0


# ---------------------------------------------------------------------------
# Power analysis
# ---------------------------------------------------------------------------


def test_required_n_matches_power() -> None:
    # n computed for 80% power should actually deliver >= 80% power.
    n = required_n_for_effect(effect=10.0, sd_diff=14.0, power=0.8)
    assert n >= 2
    assert power_for_n(10.0, 14.0, n) >= 0.8
    # One fewer seed should drop below target (the ceil boundary is tight).
    assert power_for_n(10.0, 14.0, n - 1) < 0.8 + 1e-9


def test_power_increases_with_n() -> None:
    p_small = power_for_n(5.0, 20.0, 5)
    p_large = power_for_n(5.0, 20.0, 50)
    assert 0.0 <= p_small < p_large <= 1.0


def test_required_n_zero_sd_is_floor() -> None:
    # Deterministic differences: 2 seeds suffice (the SD-estimate floor).
    assert required_n_for_effect(effect=5.0, sd_diff=0.0) == 2


def test_required_n_zero_effect_raises() -> None:
    with pytest.raises(ValueError):
        required_n_for_effect(effect=0.0, sd_diff=10.0)


# ---------------------------------------------------------------------------
# Variance decomposition
# ---------------------------------------------------------------------------


def test_variance_pure_between() -> None:
    # Identical replicates within each seed -> within=0, all variance is between.
    vc = variance_components([[10.0, 10.0], [20.0, 20.0]])
    assert vc.n_seeds == 2
    assert vc.repeats == 2
    assert math.isclose(vc.sd_within, 0.0, abs_tol=1e-12)
    assert math.isclose(vc.sd_between, math.sqrt(50.0), rel_tol=1e-9)
    assert math.isclose(vc.icc, 1.0, rel_tol=1e-9)


def test_variance_pure_within() -> None:
    # Identical group means -> between=0, all variance is within (LLM sampling).
    vc = variance_components([[10.0, 20.0], [10.0, 20.0]])
    assert math.isclose(vc.sd_between, 0.0, abs_tol=1e-12)
    assert math.isclose(vc.sd_within, math.sqrt(50.0), rel_tol=1e-9)
    assert math.isclose(vc.icc, 0.0, abs_tol=1e-12)


def test_variance_total_is_model_implied() -> None:
    # σ_total² == σ_within² + σ_between² so the decomposition reads cleanly.
    vc = variance_components([[10.0, 14.0], [20.0, 28.0]])
    assert math.isclose(
        vc.sd_total**2, vc.sd_within**2 + vc.sd_between**2, rel_tol=1e-9
    )


def test_variance_empty() -> None:
    vc = variance_components([])
    assert vc.n_seeds == 0
    assert vc.icc == 0.0
