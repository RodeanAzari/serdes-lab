"""Gaussian noise generator (model/noise.py, ADR 0003/0005): bit-exact reference for the RTL.

Accuracy checks are exact: pmf_g enumerates every one of the 2^63 magnitude inputs by group.
"""

import math

import numpy as np
import pytest
from scipy.special import ndtr, ndtri

from model import noise as nz

CFG = nz.NoiseCfg()
SIGMA_REGS = [round(s * (1 << CFG.sigma_frac)) for s in (49.4, 76.4, 102.0, 157.0)]


@pytest.fixture(scope="module")
def tb() -> nz.Tables:
    return nz.build_tables(CFG)


@pytest.fixture(scope="module")
def cg(tb: nz.Tables) -> np.ndarray:
    return nz.pmf_g(tb)


def ref_mag(u: int, tb: nz.Tables) -> int:
    """Independent pure-int model of one sample: the addressing the RTL implements."""
    c = tb.cfg
    s, xb, t_bits = c.sub_bits, c.x_bits, c.sub_bits + c.x_bits
    if u == 0:
        seg, x = 63 << s, 0
    else:
        b = u.bit_length() - 1  # bits after the leading one
        v = u - (1 << b)
        w = v >> (b - t_bits) if b >= t_bits else v << (t_bits - b)
        seg, x = ((62 - b) << s) + (w >> xb), w & ((1 << xb) - 1)
    c0, c1, c2 = int(tb.c0[seg]), int(tb.c1[seg]), int(tb.c2[seg])
    t = c1 + ((x * c2 + (1 << (xb - 1))) >> xb)
    sh = xb + c.guard
    return max(0, c0 + ((x * t + (1 << (sh - 1))) >> sh))


def edge_inputs() -> list[int]:
    """Every octave boundary, its neighbours, sub-segment edges of octave 0, extremes."""
    us = {0, 1, 2, 3, (1 << 63) - 1}
    for b in range(63):
        us |= {1 << b, (1 << b) + 1, (1 << (b + 1)) - 1}
    t_bits = CFG.sub_bits + CFG.x_bits
    for k in range(1 << CFG.sub_bits):
        base = (1 << 62) + (k << (62 - CFG.sub_bits))
        us |= {base, base - 1, base + (1 << (62 - t_bits)) - 1}
    return sorted(u for u in us if 0 <= u < (1 << 63))


def test_leading_zeros_matches_bit_length() -> None:
    rng = np.random.default_rng(5)
    us = [int(v) >> int(k) for v, k in zip(rng.integers(0, 1 << 63, 5000, dtype=np.uint64),
                                           rng.integers(0, 64, 5000), strict=True)]  # fmt: skip
    us += edge_inputs()
    got = nz.leading_zeros63(np.array(us, dtype=np.uint64))
    assert [int(g) for g in got] == [63 - u.bit_length() for u in us]


def test_vector_path_matches_int_reference(tb: nz.Tables) -> None:
    # Random inputs at every scale (shifted so all octaves are hit) plus every boundary.
    rng = np.random.default_rng(6)
    us = [int(v) >> int(k) for v, k in zip(rng.integers(0, 1 << 63, 20000, dtype=np.uint64),
                                           rng.integers(0, 64, 20000), strict=True)]  # fmt: skip
    us += edge_inputs()
    got = nz.gauss_mag(np.array(us, dtype=np.uint64), tb)
    assert [int(g) for g in got] == [ref_mag(u, tb) for u in us]


def test_known_quantiles(tb: nz.Tables) -> None:
    # |g| = Qinv(p/2), p = (u + 1/2) / 2^63: u = 2^62 is the median of |G| (0.6745),
    # u = 0 the deepest point (p = 2^-64, 9.155 sigma), u = 2^63 - 1 nearly zero.
    lsb = 2.0**-CFG.g_frac
    g = nz.gauss_mag(np.array([1 << 62, 0, (1 << 63) - 1, 1], dtype=np.uint64), tb) * lsb
    assert g[0] == pytest.approx(-ndtri(0.25), abs=1e-5)
    assert g[1] == pytest.approx(-ndtri(2.0**-65), abs=1e-5) and g[1] > 9.15
    assert g[2] == pytest.approx(0.0, abs=1e-5)
    assert g[3] == pytest.approx(-ndtri(0.75 * 2.0**-63), abs=1e-5)


def test_per_input_accuracy(tb: nz.Tables) -> None:
    # Against the ideal for each individual input (not the group centre): fit error plus the
    # spread of a group (2^-(T+1) of p in octave 0) must stay far below the tail budget.
    rng = np.random.default_rng(7)
    u = rng.integers(0, 1 << 63, 200_000, dtype=np.uint64) >> rng.integers(0, 63, 200_000).astype(
        np.uint64)
    g = nz.gauss_mag(u, tb) * 2.0**-CFG.g_frac
    ideal = nz.g_ideal((u.astype(np.float64) + 0.5) * 2.0**-63)
    assert np.max(np.abs(g - ideal)) < 1e-5


def test_exact_mass_and_reach(cg: np.ndarray) -> None:
    assert int(cg.sum()) == 1 << 63
    assert (len(cg) - 1) * 2.0**-CFG.g_frac > 9.0  # reach past 8 sigma with margin (ADR 0003)


def test_tail_within_one_percent_to_8_sigma(cg: np.ndarray) -> None:
    # ADR 0003 target, exact: P_gen(|g| >= t) vs an exact Gaussian rounded the same way.
    err, _ = nz.tail_ratio_err(cg, 2.0**-CFG.g_frac, 8.0)
    assert err <= 0.01


@pytest.mark.parametrize("sigma_reg", SIGMA_REGS)
def test_scaled_noise_tail_and_variance(cg: np.ndarray, sigma_reg: int) -> None:
    # After the sigma scale and rounding to pre-ADC units, at the operating-point sigmas.
    sig = sigma_reg / (1 << CFG.sigma_frac)
    cn = nz.pmf_n(cg, sigma_reg, CFG)
    assert int(cn.sum()) == 1 << 63
    err, _ = nz.tail_ratio_err(cn, 1.0 / sig, 8.0)
    assert err <= 0.01
    # Exact second moment (sign symmetric) vs the same-rounded Gaussian's, ~sigma^2 + 1/12.
    m = np.arange(len(cn), dtype=np.float64)
    var_gen = float(np.sum(cn.astype(np.float64) * m**2)) / 2.0**63
    mm = np.arange(1, int(12 * sig))
    p_ideal = 2.0 * (ndtr(-(mm - 0.5) / sig) - ndtr(-(mm + 0.5) / sig))
    var_ideal = float(np.sum(p_ideal * mm**2))
    assert var_gen == pytest.approx(var_ideal, rel=1e-5)
    assert var_ideal == pytest.approx(sig**2 + 1 / 12, rel=1e-4)


def test_sign_applied_after_rounding_is_symmetric(tb: nz.Tables) -> None:
    # Rounding then negating gives an exactly symmetric pmf (zero mean, no DC bias, cf. the
    # double-rounding bias in ADR 0004). Negating before rounding half-up would not.
    rng = np.random.default_rng(8)
    u = rng.integers(0, 1 << 63, 50_000, dtype=np.uint64)
    neg = u | np.uint64(1 << 63)
    for sr in SIGMA_REGS:
        assert np.array_equal(nz.noise(neg, tb, sr), -nz.noise(u, tb, sr))


def test_scale_range_and_saturation(tb: nz.Tables) -> None:
    with pytest.raises(ValueError):
        nz.scale(np.array([1]), 1 << CFG.sigma_bits, CFG)
    with pytest.raises(ValueError):
        nz.scale(np.array([1]), -1, CFG)
    top = (1 << (CFG.noise_bits - 1)) - 1
    g_max = nz.gauss_mag(np.array([0], dtype=np.uint64), tb)
    assert int(nz.scale(g_max, (1 << CFG.sigma_bits) - 1, CFG)[0]) == top  # saturates, no wrap
    # Largest sigma that never saturates (pre-ADC word headroom, docs/fixed-point.md).
    s_ok = math.floor(top / (int(g_max[0]) * 2.0**-CFG.g_frac) * (1 << CFG.sigma_frac))
    assert int(nz.scale(g_max, s_ok, CFG)[0]) <= top


def test_chi2_noncentrality_is_zero_for_the_ideal_pmf() -> None:
    # The rounded Gaussian itself, as 2^63-scaled counts, must show no excess.
    sig = 49.4
    m = np.arange(1, int(12 * sig))
    p = 2.0 * (ndtr(-(m - 0.5) / sig) - ndtr(-(m + 0.5) / sig))
    counts = np.round(np.concatenate(([1.0 - p.sum()], p)) * 2.0**63).astype(np.uint64)
    for t_lo in (0.0, 4.0):
        lam, dof = nz.chi2_noncentrality(counts, sig, 4e13, t_lo)
        assert lam < 1e-3 and dof > 100


def test_hw_tail_chi2_cannot_reject_bug_free_generator(cg: np.ndarray) -> None:
    # ADR 0005 hardware plan: 4e13 samples at sigma_reg for 49.4, Gaussian chi-square on
    # |n| >= 4 sigma only. Expected excess must sit far inside the statistic's spread
    # sqrt(2 dof), or a correct RTL would fail the test.
    sr = SIGMA_REGS[0]
    lam, dof = nz.chi2_noncentrality(nz.pmf_n(cg, sr, CFG), sr / (1 << CFG.sigma_frac), 4e13, 4.0)
    assert lam < 0.5 * math.sqrt(2 * dof)


def test_chi2_noncentrality_known_perturbation() -> None:
    # Moving probability d from bin 1 to bin 2 gives lambda = N d^2 (1/p1 + 1/p2) exactly.
    sig, n, d = 49.4, 4e13, 1e-7
    m = np.arange(1, int(12 * sig))
    p = np.concatenate(([0.0], 2.0 * (ndtr(-(m - 0.5) / sig) - ndtr(-(m + 0.5) / sig))))
    p[0] = 1.0 - p[1:].sum()
    q = p.copy()
    q[1] -= d
    q[2] += d
    counts = np.round(q * 2.0**63).astype(np.uint64)
    lam, _ = nz.chi2_noncentrality(counts, sig, n)
    assert lam == pytest.approx(n * d**2 * (1 / p[1] + 1 / p[2]), rel=1e-3)
