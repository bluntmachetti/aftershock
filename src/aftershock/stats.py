"""Pure-stdlib statistics for the measurement harness (Tier 0).

Everything here is dependency-free (math + random only) so the project keeps its
lean install, and every routine is deterministic: the bootstrap uses a fixed,
explicitly-passed seed (never system entropy), so an ABLATION.md is byte-stable
across re-runs of the *analysis* given the same inputs.

Nothing in this module touches the simulation path — it post-processes recorded
``lives_saved`` numbers — so Invariant 1 (engine determinism) is unaffected.

The framing (see docs/FOLLOWUPS.md): the LLM arms are *not* reproducible
run-to-run, so a +5-life "improvement" on n=5 seeds can easily be noise. These
helpers turn a pile of paired per-seed numbers into a believable verdict: a
paired effect, a sign-test p-value, a bootstrap CI, and a power curve answering
"how many seeds do I need to *see* a +X-life effect?".
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Descriptive statistics
# ---------------------------------------------------------------------------


def mean(xs: list[float]) -> float:
    """Arithmetic mean; 0.0 for an empty list (matches bench.aggregate)."""
    return sum(xs) / len(xs) if xs else 0.0


def sample_sd(xs: list[float]) -> float:
    """Sample standard deviation (ddof=1). 0.0 when n < 2 (matches bench)."""
    n = len(xs)
    if n < 2:
        return 0.0
    m = mean(xs)
    return math.sqrt(sum((v - m) ** 2 for v in xs) / (n - 1))


# ---------------------------------------------------------------------------
# Normal distribution (no scipy): CDF via erf, inverse-CDF via Acklam + Halley
# ---------------------------------------------------------------------------


def norm_cdf(x: float) -> float:
    """Standard-normal CDF Φ(x), exact to double precision via math.erfc."""
    return 0.5 * math.erfc(-x / math.sqrt(2.0))


# Acklam's rational approximation coefficients for the inverse normal CDF.
_A = (
    -3.969683028665376e01,
    2.209460984245205e02,
    -2.759285104469687e02,
    1.383577518672690e02,
    -3.066479806614716e01,
    2.506628277459239e00,
)
_B = (
    -5.447609879822406e01,
    1.615858368580409e02,
    -1.556989798598866e02,
    6.680131188771972e01,
    -1.328068155288572e01,
)
_C = (
    -7.784894002430293e-03,
    -3.223964580411365e-01,
    -2.400758277161838e00,
    -2.549732539343734e00,
    4.374664141464968e00,
    2.938163982698783e00,
)
_D = (
    7.784695709041462e-03,
    3.224671290700398e-01,
    2.445134137142996e00,
    3.754408661907416e00,
)


def norm_ppf(p: float) -> float:
    """Inverse standard-normal CDF Φ⁻¹(p) for 0 < p < 1.

    Acklam's rational approximation refined by one Halley step against erfc, so
    the result is accurate to roughly machine precision across the whole range.
    """
    if not 0.0 < p < 1.0:
        raise ValueError(f"norm_ppf requires 0 < p < 1, got {p!r}")

    p_low = 0.02425
    p_high = 1.0 - p_low

    if p < p_low:
        q = math.sqrt(-2.0 * math.log(p))
        x = (((((_C[0] * q + _C[1]) * q + _C[2]) * q + _C[3]) * q + _C[4]) * q + _C[5]) / (
            (((_D[0] * q + _D[1]) * q + _D[2]) * q + _D[3]) * q + 1.0
        )
    elif p <= p_high:
        q = p - 0.5
        r = q * q
        x = (((((_A[0] * r + _A[1]) * r + _A[2]) * r + _A[3]) * r + _A[4]) * r + _A[5]) * q / (
            ((((_B[0] * r + _B[1]) * r + _B[2]) * r + _B[3]) * r + _B[4]) * r + 1.0
        )
    else:
        q = math.sqrt(-2.0 * math.log(1.0 - p))
        x = -(((((_C[0] * q + _C[1]) * q + _C[2]) * q + _C[3]) * q + _C[4]) * q + _C[5]) / (
            (((_D[0] * q + _D[1]) * q + _D[2]) * q + _D[3]) * q + 1.0
        )

    # One Halley refinement step.
    e = norm_cdf(x) - p
    u = e * math.sqrt(2.0 * math.pi) * math.exp(x * x / 2.0)
    x = x - u / (1.0 + x * u / 2.0)
    return x


# ---------------------------------------------------------------------------
# Paired difference test (sign test + bootstrap CI)
# ---------------------------------------------------------------------------


def sign_test_p(diffs: list[float]) -> float:
    """Two-sided exact binomial sign test p-value for paired differences.

    H0: P(treatment > control) = 0.5. Ties (diff == 0) are dropped (standard).
    Returns 1.0 when there are no non-zero differences.
    """
    pos = sum(1 for d in diffs if d > 0)
    neg = sum(1 for d in diffs if d < 0)
    n = pos + neg
    if n == 0:
        return 1.0
    k = min(pos, neg)
    tail = sum(math.comb(n, i) for i in range(k + 1)) * (0.5**n)
    return min(1.0, 2.0 * tail)


@dataclass(frozen=True)
class BootstrapCI:
    lower: float
    upper: float
    confidence: float
    n_resamples: int


def bootstrap_ci(
    diffs: list[float],
    confidence: float = 0.95,
    n_resamples: int = 10000,
    rng_seed: int = 0,
) -> BootstrapCI:
    """Percentile bootstrap CI for the *mean* of the paired differences.

    Deterministic: the resampling RNG is seeded from ``rng_seed`` (never system
    entropy), so the interval is reproducible for a given input + seed.
    """
    if not diffs:
        return BootstrapCI(0.0, 0.0, confidence, n_resamples)
    if len(diffs) == 1:
        d = diffs[0]
        return BootstrapCI(d, d, confidence, n_resamples)

    rng = random.Random(rng_seed)
    n = len(diffs)
    means: list[float] = []
    for _ in range(n_resamples):
        sample = [diffs[rng.randrange(n)] for _ in range(n)]
        means.append(sum(sample) / n)
    means.sort()
    alpha = 1.0 - confidence
    lo_idx = max(0, int(math.floor((alpha / 2.0) * n_resamples)))
    hi_idx = min(n_resamples - 1, int(math.ceil((1.0 - alpha / 2.0) * n_resamples)) - 1)
    return BootstrapCI(means[lo_idx], means[hi_idx], confidence, n_resamples)


# ---------------------------------------------------------------------------
# Power analysis (paired design, normal approximation)
# ---------------------------------------------------------------------------


def power_for_n(effect: float, sd_diff: float, n: int, alpha: float = 0.05) -> float:
    """Power of a two-sided paired test to detect ``effect`` at sample size ``n``.

    Normal (z) approximation on the paired differences:
        power = Φ( |effect|/σ_d · √n − z_{1−α/2} )
    This understates the small-n penalty of the exact t-test slightly, so it is a
    mild upper bound — honest enough for "do I have any chance of seeing this?".
    Returns 0.0 when σ_d == 0 and effect == 0 (nothing to detect).
    """
    if n < 1:
        return 0.0
    if sd_diff <= 0.0:
        # Zero-variance differences: any non-zero effect is detected with certainty.
        return 1.0 if effect != 0.0 else 0.0
    z_alpha = norm_ppf(1.0 - alpha / 2.0)
    ncp = abs(effect) / sd_diff * math.sqrt(n)
    return norm_cdf(ncp - z_alpha)


def required_n_for_effect(
    effect: float,
    sd_diff: float,
    power: float = 0.8,
    alpha: float = 0.05,
) -> int:
    """Smallest paired sample size to detect ``effect`` at the target ``power``.

    Inverts the z-approximation:
        n = ((z_{1−α/2} + z_{power}) · σ_d / effect)²
    Returns 2 (the floor for a paired SD estimate) when σ_d == 0 or effect == 0
    is degenerate; rounds up. ``effect`` must be non-zero.
    """
    if effect == 0.0:
        raise ValueError("effect must be non-zero")
    if sd_diff <= 0.0:
        return 2
    z_alpha = norm_ppf(1.0 - alpha / 2.0)
    z_power = norm_ppf(power)
    n = ((z_alpha + z_power) * sd_diff / abs(effect)) ** 2
    return max(2, math.ceil(n))


# ---------------------------------------------------------------------------
# One-way random-effects variance decomposition (M2: repeats per seed)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class VarianceComponents:
    """Within-seed (LLM sampling) vs between-seed (world) variance split.

    ``icc`` (intraclass correlation) = σ²_between / (σ²_between + σ²_within): the
    fraction of total variance that is the *world*, not the model's stochasticity.
    """

    n_seeds: int
    repeats: int
    grand_mean: float
    sd_within: float
    sd_between: float
    sd_total: float
    icc: float


def variance_components(groups: list[list[float]]) -> VarianceComponents:
    """Decompose variance into within-group and between-group components.

    ``groups`` is one list of replicate values per seed (balanced design assumed;
    unequal group sizes use the average group size for the between estimator, a
    standard approximation). Within = LLM sampling noise; between = world spread.
    """
    groups = [g for g in groups if g]
    s = len(groups)
    if s == 0:
        return VarianceComponents(0, 0, 0.0, 0.0, 0.0, 0.0, 0.0)

    sizes = [len(g) for g in groups]
    group_means = [mean(g) for g in groups]
    all_vals = [v for g in groups for v in g]
    grand = mean(all_vals)

    # Within: pooled across groups (only groups with >= 2 replicates contribute df).
    ss_within = sum((v - gm) ** 2 for g, gm in zip(groups, group_means, strict=True) for v in g)
    df_within = sum(sz - 1 for sz in sizes)
    msw = ss_within / df_within if df_within > 0 else 0.0

    # Between: MSB uses K * Σ(group_mean - grand)². With unequal sizes use mean K.
    avg_k = sum(sizes) / s
    ss_between = avg_k * sum((gm - grand) ** 2 for gm in group_means)
    df_between = s - 1
    msb = ss_between / df_between if df_between > 0 else 0.0

    var_within = msw
    var_between = max(0.0, (msb - msw) / avg_k) if avg_k > 0 else 0.0
    denom = var_between + var_within
    icc = var_between / denom if denom > 0 else 0.0

    # Model-implied total so the table reads as a clean decomposition:
    # σ_total² = σ_within² + σ_between² (NOT the raw pooled sample SD, which uses a
    # different df correction and can confusingly print smaller than σ_between).
    return VarianceComponents(
        n_seeds=s,
        repeats=round(avg_k),
        grand_mean=grand,
        sd_within=math.sqrt(var_within),
        sd_between=math.sqrt(var_between),
        sd_total=math.sqrt(var_within + var_between),
        icc=icc,
    )
