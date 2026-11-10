"""Gaussian noise generator: segmented inverse CDF (ADR 0003), bit-exact reference for the RTL.

One 64-bit uniform word per sample: bit 63 = sign s, bits 62:0 = magnitude input u.

    p   = (u + 1/2) / 2^63                    (0, 1)
    |g| = Qinv(p / 2)                          ideal: P(|G| > g) = 2 Q(g)
    octave o = leading zeros of u in 63 bits   (0..62; u = 0 is octave 63)
    w   = the T = S + XB bits after the leading one (left-aligned, zero-padded when fewer exist)
    seg = o * 2^S + (w >> XB),   x = w mod 2^XB
    t   = c1[seg] + rs(x * c2[seg], XB)                       units 2^-F1, F1 = FG + G
    g   = max(0, c0[seg] + rs(x * t, XB + G))                 units 2^-FG (unsigned magnitude)
    n   = sat(rs(g * sigma_reg, FG + FSIG), NOISE_BITS)       pre-ADC units (2^-6 ADC LSB)
    out = s ? -n : n                                          sign last: exactly symmetric pmf

rs = round half up (fixed.round_shift). Two multiplies (x*c2, x*t) and the sigma scale are one
DSP48E1 each: x is XB <= 17 b unsigned (18 b port), c2, t and g fit the 25 b port.

The map u -> g is a fixed function of one uniform input, so its output distribution is computed
EXACTLY by enumerating every (segment, x) group with its integer input count (`pmf_g`); no
sampling is involved anywhere in the accuracy checks.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import numpy.typing as npt
from scipy.special import ndtr, ndtri  # type: ignore[import-untyped]

from model.fixed import round_shift, sat

IArr = npt.NDArray[np.int64]
UArr = npt.NDArray[np.uint64]
FArr = npt.NDArray[np.float64]

U_BITS = 63
N_OCT = 64  # octaves 0..62 plus u = 0


@dataclass(frozen=True)
class NoiseCfg:
    sub_bits: int = 4  # S: sub-segments per octave = 2^S
    x_bits: int = 17  # XB: polynomial input bits
    g_frac: int = 20  # FG: output magnitude fractional bits
    guard: int = 6  # G: extra fractional bits on c1, c2, t
    sigma_frac: int = 5  # FSIG: sigma register fractional bits
    sigma_bits: int = 17  # sigma register width, unsigned (DSP 18 b port)
    noise_bits: int = 16  # noise sample, signed, = pre-ADC word width


@dataclass(frozen=True)
class Tables:
    c0: IArr  # units 2^-FG, indexed by seg = o * 2^S + sub
    c1: IArr  # units 2^-F1
    c2: IArr  # units 2^-F1
    cfg: NoiseCfg


def g_ideal(p: FArr) -> FArr:
    """|g| with P(|G| > |g|) = p."""
    return np.asarray(-ndtri(p / 2.0), dtype=np.float64)


def _octave_groups(o: int, cfg: NoiseCfg) -> tuple[IArr, int, FArr]:
    """Valid aligned words w for octave o, the input count per w, and each group's centre p."""
    t_bits = cfg.sub_bits + cfg.x_bits
    b = U_BITS - 1 - o  # bits after the leading one
    if b >= t_bits:
        w = np.arange(1 << t_bits, dtype=np.int64)
        weight, half = 1 << (b - t_bits), 0.5
    else:
        w = np.arange(1 << b, dtype=np.int64) << (t_bits - b)
        weight, half = 1, 0.5 * (1 << (t_bits - b))
    p = 2.0 ** -(o + 1) * (1.0 + (w + half) / float(1 << t_bits))
    return w, weight, np.asarray(p, dtype=np.float64)


def _eval(seg: IArr, x: IArr, tb: Tables) -> IArr:
    c = tb.cfg
    t = tb.c1[seg] + round_shift(x * tb.c2[seg], c.x_bits)
    g = tb.c0[seg] + round_shift(x * t, c.x_bits + c.guard)
    return np.asarray(np.maximum(g, 0), dtype=np.int64)


def build_tables(cfg: NoiseCfg) -> Tables:
    """Least-squares degree-2 fit per segment on the group centres, coefficients rounded, then
    c0 re-centred so the integer evaluation's error is balanced (approximately minimax)."""
    s, xb, fg, f1 = cfg.sub_bits, cfg.x_bits, cfg.g_frac, cfg.g_frac + cfg.guard
    n_seg = N_OCT << s
    c0, c1, c2 = (np.zeros(n_seg, dtype=np.int64) for _ in range(3))
    c0[(N_OCT - 1) << s] = round(float(g_ideal(np.array([0.5 * 2.0**-U_BITS]))[0]) * (1 << fg))
    for o in range(N_OCT - 1):
        w, _, p = _octave_groups(o, cfg)
        target = g_ideal(p)
        sub, x = w >> xb, w & ((1 << xb) - 1)
        for k in np.unique(sub):
            m = sub == k
            xk, yk = x[m], target[m]
            idx = np.unique(np.linspace(0, len(xk) - 1, min(len(xk), 513)).astype(np.int64))
            xf = xk[idx] / float(1 << xb)
            deg = min(2, len(idx) - 1)
            coef = np.polynomial.polynomial.polyfit(xf, yk[idx], deg) if deg > 0 else yk[idx]
            coef = np.pad(np.asarray(coef, dtype=np.float64), (0, 3 - len(coef)))
            seg = (o << s) + int(k)
            c1[seg], c2[seg] = round(coef[1] * (1 << f1)), round(coef[2] * (1 << f1))
            c0[seg] = round(coef[0] * (1 << fg))
            tb = Tables(c0, c1, c2, cfg)
            err = _eval(np.full(len(xk), seg), xk, tb) - yk * (1 << fg)
            c0[seg] -= round(0.5 * (float(err.max()) + float(err.min())))
    return Tables(c0, c1, c2, cfg)


def fit_stats(tb: Tables) -> dict[str, int | float]:
    """Max |g - g_ideal(group centre)| in sigma, and the signed widths (bits) the tables and
    the Horner intermediate t need, over every evaluated (segment, x)."""
    c = tb.cfg
    err, t_ext = 0.0, [0]
    for o in range(N_OCT - 1):
        w, _, p = _octave_groups(o, c)
        seg, x = (o << c.sub_bits) + (w >> c.x_bits), w & ((1 << c.x_bits) - 1)
        err = max(err, float(np.max(np.abs(_eval(seg, x, tb) / float(1 << c.g_frac) - g_ideal(p)))))
        t = tb.c1[seg] + round_shift(x * tb.c2[seg], c.x_bits)
        t_ext += [int(t.min()), int(t.max())]

    def sbits(v: list[int] | IArr) -> int:
        return int(max(abs(int(np.min(v))), abs(int(np.max(v))))).bit_length() + 1

    return {"max_err_sigma": err, "c0_bits": sbits(tb.c0), "c1_bits": sbits(tb.c1),
            "c2_bits": sbits(tb.c2), "t_bits": sbits(t_ext)}  # fmt: skip


def leading_zeros63(u: UArr) -> IArr:
    """Leading-zero count of a 63-bit value (63 for u = 0)."""
    u = np.asarray(u, dtype=np.uint64)
    n = np.zeros(u.shape, dtype=np.int64)
    v = u.copy()
    for sh in (32, 16, 8, 4, 2, 1):
        top_empty = (v >> np.uint64(U_BITS - sh)) == 0
        n += np.where(top_empty, sh, 0)
        v = np.where(top_empty, (v << np.uint64(sh)) & np.uint64((1 << U_BITS) - 1), v)
    return np.where(u == 0, U_BITS, n)


def gauss_mag(u: UArr, tb: Tables) -> IArr:
    """Integer |g| (units 2^-FG) for 63-bit inputs u: the per-sample path the RTL implements."""
    c = tb.cfg
    t_bits = c.sub_bits + c.x_bits
    u = np.asarray(u, dtype=np.uint64)
    o = leading_zeros63(u)
    b = np.maximum(U_BITS - 1 - o, 0)
    v = (u & ((np.uint64(1) << b.astype(np.uint64)) - np.uint64(1))).astype(np.int64)
    w = np.where(b >= t_bits, v >> np.maximum(b - t_bits, 0), v << np.maximum(t_bits - b, 0))
    seg = (o << c.sub_bits) + (w >> c.x_bits)
    return _eval(seg, w & ((1 << c.x_bits) - 1), tb)


def scale(g: IArr, sigma_reg: int, cfg: NoiseCfg) -> IArr:
    """Noise magnitude in pre-ADC units: g * sigma, rounded, saturated."""
    if not 0 <= sigma_reg < (1 << cfg.sigma_bits):
        raise ValueError("sigma_reg out of range")
    return sat(round_shift(g * sigma_reg, cfg.g_frac + cfg.sigma_frac), cfg.noise_bits)


def noise(word: UArr, tb: Tables, sigma_reg: int) -> IArr:
    """Signed noise samples from 64-bit uniform words (bit 63 = sign)."""
    word = np.asarray(word, dtype=np.uint64)
    n = scale(gauss_mag(word & np.uint64((1 << U_BITS) - 1), tb), sigma_reg, tb.cfg)
    return np.where((word >> np.uint64(U_BITS)) == 1, -n, n)


def pmf_g(tb: Tables) -> UArr:
    """Exact pmf of |g|: count[k] = number of the 2^63 inputs u with |g| = k (sums to 2^63)."""
    c = tb.cfg
    count = np.zeros(0, dtype=np.uint64)
    for o in range(N_OCT):
        if o == N_OCT - 1:
            g, weight = np.maximum(tb.c0[[o << c.sub_bits]], 0), 1
        else:
            w, weight, _ = _octave_groups(o, c)
            g = _eval((o << c.sub_bits) + (w >> c.x_bits), w & ((1 << c.x_bits) - 1), tb)
        h = np.bincount(g).astype(np.uint64) * np.uint64(weight)
        if len(h) > len(count):
            count = np.pad(count, (0, len(h) - len(count)))
        count[: len(h)] += h
    return count


def pmf_n(count_g: UArr, sigma_reg: int, cfg: NoiseCfg) -> UArr:
    """Exact pmf of |n| (scaled, rounded magnitude) from the |g| pmf; same 2^63 total."""
    n = scale(np.arange(len(count_g), dtype=np.int64), sigma_reg, cfg)
    out = np.zeros(int(np.max(n)) + 1, dtype=np.uint64)
    cum = np.concatenate(([np.uint64(0)], np.cumsum(count_g, dtype=np.uint64)))
    last = np.searchsorted(n, np.arange(len(out)), side="right")  # n is nondecreasing in g
    first = np.searchsorted(n, np.arange(len(out)), side="left")
    out[:] = cum[last] - cum[first]
    return out


def tail_ratio_err(count: UArr, step: float, t_max: float) -> tuple[float, float]:
    """Worst |P_gen(|X| >= k) / P_ideal(|X| >= k) - 1| over output levels k with k*step <= t_max,
    where X is the integer output, step its size in sigma, and the ideal is the same rounding
    (half up) of an exact Gaussian: P_ideal(|X| >= k) = 2 Q((k - 1/2) * step), k >= 1.
    Returns (worst error, threshold in sigma where it occurs)."""
    tail = np.cumsum(count[::-1], dtype=np.uint64)[::-1].astype(np.float64) / 2.0**U_BITS
    k = np.arange(1, min(len(count) - 1, int(t_max / step)) + 1)
    ideal = 2.0 * ndtr(-(k - 0.5) * step)
    err = np.abs(tail[k] / ideal - 1.0)
    i = int(np.argmax(err))
    return float(err[i]), float(k[i] * step)


def chi2_noncentrality(
    count_n: UArr, sigma: float, n_samples: float, t_lo: float = 0.0
) -> tuple[float, int]:
    """Expected chi-square excess (noncentrality) a histogram of n_samples |n| values would show
    against the rounded Gaussian, bins merged in the tail to >= 5 expected counts. With t_lo > 0
    every |n| below t_lo sigma is merged into one bin (tail-only test).
    Returns (lambda, degrees of freedom). lambda << dof: the test cannot see the generator."""
    pg = count_n.astype(np.float64) / 2.0**U_BITS
    m = np.arange(len(pg))
    upper = ndtr(-(m + 0.5) / sigma)
    pi = 2.0 * (ndtr(-np.maximum(m - 0.5, 0.0) / sigma) - upper)
    pi[0] = 1.0 - 2.0 * upper[0]
    keep = int(np.searchsorted(-(pi * n_samples), -5.0))  # pi decreasing in m
    keep = min(keep, len(pg) - 1)
    lo = min(int(np.ceil(t_lo * sigma)), keep)
    body_g, body_i = ([pg[:lo].sum()], [pi[:lo].sum()]) if lo > 0 else ([], [])
    pg_b = np.concatenate((body_g, pg[lo:keep], [pg[keep:].sum()]))
    pi_b = np.concatenate((body_i, pi[lo:keep], [2.0 * ndtr(-(keep - 0.5) / sigma)]))
    return float(n_samples * np.sum((pg_b - pi_b) ** 2 / pi_b)), len(pg_b) - 1


# ---- hardware histogram statistics (ADR 0005 validation, ADR 0009) ----------------------------


def fold_abs(hist: IArr) -> IArr:
    """|n| counts from a signed histogram whose bin b holds n = b - len(hist) // 2."""
    h = np.asarray(hist, dtype=np.int64)
    c = len(h) // 2
    out = h[c:].copy()
    out[1 : c + 1] += h[c - 1 :: -1][: len(out) - 1]
    return out


def gauss_abs_pmf(sigma: float, n_max: int) -> FArr:
    """P(|X| = m), m = 0..n_max, X = an exact N(0, sigma^2) rounded half up; the mass beyond
    n_max is added to the last entry so the vector sums to 1."""
    m = np.arange(n_max + 1)
    upper = ndtr(-(m + 0.5) / sigma)
    p = 2.0 * (ndtr(-np.maximum(m - 0.5, 0.0) / sigma) - upper)
    p[0] = 1.0 - 2.0 * upper[0]
    p[-1] += 2.0 * upper[-1]
    return np.asarray(p, dtype=np.float64)


def chi2_gof(obs: IArr, p: FArr, lo: int = 0) -> tuple[float, int, float]:
    """Pearson chi-square of |n| counts against the pmf p (same indexing, sums to 1).
    Bins below lo are merged into one (tail-only test, ADR 0005); upward, bins are kept
    singly while the expected count is >= 5 and the rest is merged into one tail bin.
    Returns (statistic, degrees of freedom, p-value)."""
    from scipy.stats import chi2 as chi2_dist  # type: ignore[import-untyped]

    o = np.zeros(max(len(obs), len(p)), dtype=np.float64)
    o[: len(obs)] = obs
    q = np.zeros(len(o), dtype=np.float64)
    q[: len(p)] = p
    e = q * o.sum()
    keep = int(np.argmax(e < 5.0)) if np.any(e < 5.0) else len(e)
    keep = min(max(keep, lo + 1), len(o) - 1)  # reduceat needs every edge < len(o)
    edges = ([0] if lo > 0 else []) + list(range(lo, keep)) + [keep]
    ob = np.add.reduceat(o, edges)
    eb = np.add.reduceat(e, edges)
    stat = float(np.sum((ob - eb) ** 2 / eb))
    dof = len(ob) - 1
    return stat, dof, float(chi2_dist.sf(stat, dof))


def symmetry_test(hist: IArr) -> tuple[float, int, float]:
    """Counts at +m vs -m (m >= 1, pairs with >= 10 samples): sum (a - b)^2 / (a + b), which is
    chi-square with one dof per pair if the pmf is symmetric. Returns (stat, dof, p-value)."""
    from scipy.stats import chi2 as chi2_dist

    h = np.asarray(hist, dtype=np.float64)
    c = len(h) // 2
    a, b = h[c + 1 :], h[c - 1 :: -1][: len(h) - c - 1]
    use = (a + b) >= 10
    stat = float(np.sum((a[use] - b[use]) ** 2 / (a[use] + b[use])))
    dof = int(np.count_nonzero(use))
    return stat, dof, float(chi2_dist.sf(stat, dof))
