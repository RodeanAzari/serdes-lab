"""KP4 statistics (model/fec_stats.py) and the end-to-end KP4 link (model/kp4link.py)."""

import numpy as np
import pytest
from scipy.stats import binom

from model import fec_stats as fs
from model import rs
from model.equalizer import mmse_ffe_dfe
from model.kp4link import BITS_PER_CW, decode_mismatches, run_kp4
from model.link import noise_sigma
from model.stats import clopper_pearson

IDEAL, ONE = np.array([1.0]), np.array([1.0])


def test_errors_per_codeword_grouping() -> None:
    lane = np.zeros(2 * rs.N, dtype=bool)
    lane[[0, 1, 2, 543, 544, 1087]] = True
    # Non-interleaved: positions 0..543 are codeword 0, 544..1087 codeword 1.
    assert list(fs.errors_per_codeword(lane, 1)) == [4, 2]
    # 2-way: A takes even lane positions, B odd (A0 B0 A1 B1 ...):
    # 0, 2, 544 -> A; 1, 543, 1087 -> B.
    assert list(fs.errors_per_codeword(lane, 2)) == [3, 3]
    # A burst of 2 adjacent RS symbols hits both codewords once when interleaved.
    burst = np.zeros(2 * rs.N, dtype=bool)
    burst[100:102] = True
    assert list(fs.errors_per_codeword(burst, 1)) == [2, 0]
    assert list(fs.errors_per_codeword(burst, 2)) == [1, 1]
    with pytest.raises(ValueError):
        fs.errors_per_codeword(np.zeros(rs.N, dtype=bool), 2)  # half an interleaved block
    with pytest.raises(ValueError):
        fs.errors_per_codeword(lane, 3)


def test_histogram_top_bin_is_16_plus() -> None:
    h = fs.error_histogram(np.array([0, 0, 15, 16, 17, 544]))
    assert len(h) == 17 and h[0] == 2 and h[15] == 1 and h[16] == 3 and h.sum() == 6


def test_burst_lengths() -> None:
    m = np.array([1, 0, 1, 1, 1, 0, 0, 1, 1], dtype=bool)
    assert list(fs.burst_lengths(m)) == [1, 3, 2]
    assert list(fs.burst_lengths(np.zeros(5, dtype=bool))) == []
    assert list(fs.burst_lengths(np.ones(4, dtype=bool))) == [4]


def test_independent_prediction() -> None:
    p = 0.01
    assert fs.independent_cer(p) == pytest.approx(1 - binom.cdf(15, 544, p), rel=1e-9)
    h = fs.independent_histogram(p, 1000)
    assert h.sum() == pytest.approx(1000) and h[16] == pytest.approx(1000 * fs.independent_cer(p))


def test_noise_free_link_is_error_free_and_aligned() -> None:
    # The whole chain in lockstep: encode, bit order, RS-symbol alignment, precoder, demap.
    for precoder in (False, True):
        r = run_kp4(IDEAL, 0, ONE, 0, 0.0, 1.0, 1e-6, 6, 1, 2, precoder=precoder)
        assert r.bits == 6 * BITS_PER_CW and r.bit_errors == 0
        assert not r.rs_err.any() and len(r.rs_err) == 6 * rs.N and len(r.pam4_err) == 6 * 2720


def test_independent_errors_match_binomial_prediction() -> None:
    # Ideal channel, no DFE: symbol errors are independent, so the measured CER (> 15 errors)
    # must agree with the binomial prediction from the measured RS-symbol error rate. This is
    # the null case of the project's measured-vs-predicted comparison. Sigma chosen for
    # ~2% RS-symbol errors (mean ~11 per codeword, CER ~ 10%).
    r = run_kp4(IDEAL, 0, ONE, 0, 0.0, 1.0, 0.36, 3000, 3, 4, n_decode_check=40)
    n = fs.errors_per_codeword(r.rs_err, 1)
    p = float(r.rs_err.mean())
    cer_lo, cer_hi = clopper_pearson(int(np.count_nonzero(n > rs.T)), len(n))
    assert np.count_nonzero(n > rs.T) > 100
    assert cer_lo <= fs.independent_cer(p) <= cer_hi
    assert np.var(n) == pytest.approx(rs.N * p * (1 - p), rel=0.1)  # binomial dispersion
    assert r.decode_checked == 40 and r.decode_mismatches == 0  # decoder on both sides of t


def test_dfe_error_propagation_makes_bursts_and_overdispersion() -> None:
    # Real channel (31.4 dB), real-decision DFE vs ideal decisions on the same samples: error
    # propagation lengthens bursts and spreads errors-per-codeword beyond binomial.
    d = np.load("data/channels/kr_ch4_31p4db.npz")
    c, a0, a1 = int(d["cursor"]), int(d["n_pre"]), int(d["n_post"])
    p = d["pulse"][c - a0 : c + a1 + 1]
    sig = noise_sigma(p, 18.0)
    eq = mmse_ffe_dfe(p, a0, 16, 3, 1, sig**2)
    args = (p, a0, eq.taps, 3, float(eq.dfe[0]), eq.h0, sig, 400, 5, 6)
    real, ideal = run_kp4(*args), run_kp4(*args, ideal_dfe=True)
    assert real.decode_mismatches == 0 and ideal.decode_mismatches == 0
    assert fs.burst_lengths(real.pam4_err).mean() > 1.3 * fs.burst_lengths(ideal.pam4_err).mean()
    n = fs.errors_per_codeword(real.rs_err, 1)
    q = float(real.rs_err.mean())
    assert np.var(n) > 1.5 * rs.N * q * (1 - q)


def test_decode_check_at_the_t_boundary() -> None:
    # Exactly 15 errors must decode to the sent word, 16 must not: the boundary the CER
    # definition rests on. Random samples rarely land on it, so it is tested directly.
    rng = np.random.default_rng(9)
    sent = rs.encode(rng.integers(0, 1024, (2, rs.K)))
    rx = sent.copy()
    for row, k in ((0, 15), (1, 16)):
        pos = rng.choice(rs.N, k, replace=False)
        rx[row, pos] ^= rng.integers(1, 1024, k)
    assert decode_mismatches(sent, rx) == 0
    assert decode_mismatches(sent[:0], rx[:0]) == 0
