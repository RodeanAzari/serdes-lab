"""Payload PRBS31 and lfsr258 noise uniform source (model/prng.py, ADR 0003/0007).

Independent references: galois (primitivity, Berlekamp-Massey), a bit-serial Tausworthe model
built from the sequence definition in L'Ecuyer (1996/1999), naive loops, and vectors from the
reference C code (tests/data/lfsr258_ref.txt) when present.
"""

from pathlib import Path

import galois
import numpy as np
import pytest

from model import prng

GF2 = galois.GF(2)
REF = Path(__file__).parent / "data" / "lfsr258_ref.txt"


# ---- PRBS31 ----------------------------------------------------------------------------------


def naive_prbs31(n: int, seed: int) -> list[int]:
    a = [(seed >> i) & 1 for i in range(31)]
    while len(a) < n:
        a.append(a[-28] ^ a[-31])
    return a[:n]


def test_prbs31_polynomial_is_primitive() -> None:
    assert galois.Poly.Degrees([31, 28, 0]).is_primitive()


@pytest.mark.parametrize("seed", [1, 0x7FFFFFFF, 0x2AAAAAAA, 123456789])
def test_prbs31_matches_naive_recurrence(seed: int) -> None:
    n = 31 + 28 * 7 + 13  # spans several chunk boundaries, ends mid-chunk
    assert prbs31_list(n, seed) == naive_prbs31(n, seed)


def prbs31_list(n: int, seed: int) -> list[int]:
    return [int(v) for v in prng.prbs31(n, seed)]


def test_prbs31_hand_values() -> None:
    a = prng.prbs31(70, 1)  # a0 = 1, a1..a30 = 0
    assert a[0] == 1 and not a[1:31].any()
    assert a[31] == 1  # a3 ^ a0
    assert a[59] == 1  # a31 ^ a28
    assert a[62] == 1  # a34 ^ a31
    assert a[56] == 0  # a28 ^ a25


def test_prbs31_minimal_polynomial() -> None:
    """Berlekamp-Massey recovers the connection polynomial x^31 + x^3 + 1, the reciprocal of
    the characteristic polynomial x^31 + x^28 + 1."""
    bits = GF2(prng.prbs31(200, 0x1234567).astype(int))
    assert galois.berlekamp_massey(bits) == galois.Poly.Degrees([31, 3, 0])


def test_prbs31_bad_input() -> None:
    for s in (0, 1 << 31, -1):
        with pytest.raises(ValueError):
            prng.prbs31(10, s)
    with pytest.raises(ValueError):
        prng.prbs31(-1, 1)
    assert len(prng.prbs31(0, 1)) == 0
    assert prbs31_list(5, 0b10110) == [0, 1, 1, 0, 1]


# ---- lfsr258 ----------------------------------------------------------------------------------


def tausworthe_bits(y0: int, k: int, q: int, n: int) -> list[int]:
    """Sequence a[i] of one component from the definition: a[i+k] = a[i] ^ a[i+q], initial
    a[0..k-1] = the top k bits of the seed word, MSB first."""
    a = [(y0 >> (63 - i)) & 1 for i in range(k)]
    while len(a) < n:
        a.append(a[-k] ^ a[-k + q])
    return a


def test_components_match_tausworthe_definition() -> None:
    """After step m, component word bits 63..0 hold a[s*m .. s*m + 63]: each step advances the
    sequence by s. Built independently of the shift/mask code."""
    seeds = prng.lane_seeds(99, 1)[0]
    y = seeds
    steps = 6
    seqs = [tausworthe_bits(y0, k, q, 64 * steps + 64)
            for y0, (k, q, _, _) in zip(seeds, prng.LFSR258, strict=True)]
    for m in range(1, steps + 1):
        y, _ = prng.lfsr258_step(y)
        for c, (_, _, s, _) in enumerate(prng.LFSR258):
            want = sum(bit << (63 - i) for i, bit in enumerate(seqs[c][s * m : s * m + 64]))
            assert y[c] == want, (m, c)


def test_component_polynomials_are_primitive() -> None:
    for k, q, s, _ in prng.LFSR258:
        assert galois.Poly.Degrees([k, q, 0]).is_primitive()
        assert np.gcd(s, (1 << k) - 1) == 1  # decimation by s keeps the full period
        assert 0 < s <= k - q  # Tausworthe step condition


def test_output_linear_complexity_is_258() -> None:
    """Every output bit is the XOR of 5 maximal sequences of coprime-degree primitive
    polynomials: linear complexity 63+55+52+47+41 = 258."""
    w = prng.lfsr258_words(600, [prng.lane_seeds(7, 1)[0]])[:, 0]
    for bit in (0, 31, 63):
        seq = GF2(((w >> np.uint64(bit)) & np.uint64(1)).astype(int))
        assert galois.berlekamp_massey(seq).degree == 258


def test_vectorized_matches_pure_int() -> None:
    seeds = prng.lane_seeds(3, 3) + [prng.SEED_MIN]
    w = prng.lfsr258_words(50, seeds)
    for lane, s in enumerate(seeds):
        y = prng.check_seed258(s)
        for i in range(50):
            y, out = prng.lfsr258_step(y)
            assert int(w[i, lane]) == out


@pytest.mark.skipif(not REF.exists(), reason="reference vectors not generated (see file header)")
def test_matches_reference_c_code() -> None:
    """Vectors from L'Ecuyer's lfsr258.c (provenance in the data file header)."""
    cases: list[tuple[list[int], list[tuple[int, int]]]] = []
    for line in REF.read_text().splitlines():
        if line.startswith("#") or not line.strip():
            continue
        f = line.split()
        if f[0] == "seed":
            cases.append(([int(v, 16) for v in f[1:6]], []))
        else:
            cases[-1][1].append((int(f[0]), int(f[1], 16)))
    assert len(cases) >= 3
    for seed, vec in cases:
        last = max(i for i, _ in vec)
        w = prng.lfsr258_words(last + 1, [seed])[:, 0]
        for i, v in vec:
            assert int(w[i]) == v, (seed, i)


def test_seed_validation() -> None:
    ok = list(prng.SEED_MIN)
    prng.check_seed258(ok)
    for i in range(5):
        bad = ok.copy()
        bad[i] -= 1
        with pytest.raises(ValueError):
            prng.check_seed258(bad)
    with pytest.raises(ValueError):
        prng.check_seed258([1 << 64, *ok[1:]])
    with pytest.raises(ValueError):
        prng.check_seed258(ok[:4])


def test_lane_seeds_deterministic_distinct() -> None:
    a, b = prng.lane_seeds(5, 8), prng.lane_seeds(5, 8)
    assert a == b and len({w for s in a for w in s}) == 40
    assert prng.lane_seeds(6, 8) != a


@pytest.mark.parametrize("n_sym", [0, 1, 7, 8, 9, 41])
def test_noise_words_lane_mapping(n_sym: int) -> None:
    seeds = prng.lane_seeds(11, 4)
    w = prng.noise_words(n_sym, seeds)
    per_lane = prng.lfsr258_words(12, seeds)
    assert len(w) == n_sym
    for k in range(n_sym):
        assert w[k] == per_lane[k // 4, k % 4]


# ---- independence (ADR 0003 validation step 4, model side) -----------------------------------


def corr(x: np.ndarray, y: np.ndarray) -> float:
    return float(np.corrcoef(x, y)[0, 1])


def test_no_correlation_lags_lanes_payload() -> None:
    """|r| below 5/sqrt(N) for lag 1..16 within the symbol stream, across lanes, and between
    noise sign bits and payload bits. A shared or shifted generator would show |r| ~ 1."""
    n = 1 << 16
    w = prng.noise_words(n, prng.lane_seeds(1, 8))
    u = (w >> np.uint64(11)).astype(np.float64)  # top 53 bits as a float-exact uniform
    lim = 5 / np.sqrt(n)
    for lag in range(1, 17):
        assert abs(corr(u[:-lag], u[lag:])) < lim, lag
    lanes = u.reshape(-1, 8)
    lim_l = 5 / np.sqrt(len(lanes))
    for i in range(8):
        for j in range(i + 1, 8):
            assert abs(corr(lanes[:, i], lanes[:, j])) < lim_l, (i, j)
    sign = (w >> np.uint64(63)).astype(np.float64)
    pay = prng.prbs31(n, 0x5EED).astype(np.float64)
    assert abs(corr(sign, pay)) < lim
    assert abs(u.mean() / 2.0**53 - 0.5) < 5 * np.sqrt(1 / 12 / n)
