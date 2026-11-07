"""Link-model tests: mapping, DFE resolution, and that SNR/noise scaling matches theory."""

import numpy as np

from model.equalizer import mmse_ffe_dfe
from model.link import dfe1_decide, noise_sigma, run_link
from model.pam4 import (
    LEVELS,
    bits_to_gray,
    bits_to_symbols,
    gray_to_bits,
    precode,
    precode_inverse,
    slice_idx,
    symbols_to_bits,
)
from model.stats import clopper_pearson, pam4_ber_awgn, pam4_ser_awgn, upper_bound


def test_gray_mapping_matches_spec() -> None:
    # §6.1: 00 -> -3, 01 -> -1, 11 -> +1, 10 -> +3. A TX/RX mismatch looks like a bad channel.
    bits = np.array([0, 0, 0, 1, 1, 1, 1, 0], dtype=np.uint8)
    assert list(bits_to_symbols(bits)) == [-3, -1, 1, 3]
    rng = np.random.default_rng(3)
    b = rng.integers(0, 2, 1000, dtype=np.uint8)
    assert np.array_equal(symbols_to_bits(bits_to_symbols(b)), b)


def test_adjacent_levels_differ_in_one_bit() -> None:
    # The Gray property is why BER ~ SER/2; the KP4 burst analysis relies on it.
    b = symbols_to_bits(LEVELS).reshape(4, 2)
    for i in range(3):
        assert np.sum(b[i] != b[i + 1]) == 1


def test_fast_dfe_equals_sequential_loop() -> None:
    rng = np.random.default_rng(11)
    z = rng.normal(0, 2.5, 5000)
    b, h0 = 0.4, 1.0
    fast = dfe1_decide(z, b, h0, 2)
    prev, ref = 2, []
    for zk in z:
        prev = int(slice_idx(np.array([zk - b * LEVELS[prev]]), h0)[0])
        ref.append(prev)
    assert np.array_equal(fast, ref)


def test_ideal_channel_ber_matches_theory() -> None:
    # Guards the SNR definition and noise scaling: every BER curve in the project depends on it.
    snr = 16.0
    r = run_link(np.array([1.0]), 0, np.array([1.0]), 0, 0.0, 1.0, snr, 2_000_000, 1, 2)
    lo, hi = clopper_pearson(r.bit_errors, r.bits)
    assert r.bit_errors > 1000
    assert lo <= pam4_ber_awgn(snr) <= hi


def test_zero_error_upper_bound_is_rule_of_three() -> None:
    assert np.isclose(upper_bound(0, 1_000_000), 3.0 / 1_000_000, rtol=0.01)


def test_real_channel_ideal_dfe_matches_mmse_prediction() -> None:
    # With correct past decisions, the only gap to theory is non-Gaussian residual ISI (small).
    # Fails if pulse, FFE and DFE are misaligned by even one symbol. Real decisions must be
    # worse: that difference is the DFE error propagation this project measures.
    d = np.load("data/channels/kr_ch4_31p4db.npz")
    c, a0, a1 = int(d["cursor"]), int(d["n_pre"]), int(d["n_post"])
    p = d["pulse"][c - a0 : c + a1 + 1]
    eq = mmse_ffe_dfe(p, a0, 16, 3, 1, noise_sigma(p, 22.0) ** 2)
    args = (p, a0, eq.taps, 3, float(eq.dfe[0]), eq.h0, 22.0, 2_000_000, 3, 4)
    ideal = run_link(*args, ideal_dfe=True)
    real = run_link(*args)
    lo, hi = clopper_pearson(ideal.symbol_errors, ideal.symbols)
    pred = pam4_ser_awgn(eq.snr_db)
    assert 0.9 * lo <= pred <= 1.1 * hi
    assert real.symbol_errors > 1.5 * ideal.symbol_errors


# --- 1/(1+D) mod 4 precoder: IEEE Std 802.3-2022 135.5.7.2 (ADR 0006) ---


def test_gray_symbols_match_120_5_7_1() -> None:
    # {A, B}, A first: {0,0} -> 0, {0,1} -> 1, {1,1} -> 2, {1,0} -> 3.
    bits = np.array([0, 0, 0, 1, 1, 1, 1, 0], dtype=np.uint8)
    assert list(bits_to_gray(bits)) == [0, 1, 2, 3]
    assert np.array_equal(gray_to_bits(np.arange(4)), bits)


def test_precoder_matches_equations_135_1_and_135_3() -> None:
    rng = np.random.default_rng(21)
    for p_init in range(4):
        g = rng.integers(0, 4, 3000)
        prev, ref = p_init, []
        for gj in g.tolist():
            prev = (gj - prev) % 4  # Eq. 135-1
            ref.append(prev)
        p = precode(g, p_init)
        assert list(p) == ref
        ref_g = [(pj + pm) % 4 for pj, pm in zip(ref, [p_init] + ref[:-1], strict=True)]
        assert list(precode_inverse(p, p_init)) == ref_g == list(g)  # Eq. 135-3


def test_precoder_independent_worked_example() -> None:
    # Broadcom, IEEE 802.3bj Sep 2011 (parthasarathy_01_0911), "1/(1+D) Precoding worked
    # example": an independent source. Its first output (0 from input 2) implies P(-1) = 2.
    tx = [2, 2, 2, 2, 0, 3, 2, 0, 1, 3, 3, 0, 0, 0, 0, 2, 3, 0, 3]
    out = [0, 2, 0, 2, 2, 1, 1, 3, 2, 1, 2, 2, 2, 2, 2, 0, 3, 1, 2]
    assert list(precode(np.array(tx), p_init=2)) == out


def test_precoder_turns_dfe_burst_into_entry_and_exit_errors() -> None:
    # Why precoding exists (135.5.7.2 is 1/(1+D)): a 1-tap DFE burst alternates error sign,
    # +e, -e, +e, ... in the received symbols. After the (1+D) inverse, only the burst's first
    # and the first symbol after it are wrong, whatever the burst length.
    rng = np.random.default_rng(22)
    g = rng.integers(0, 4, 400)
    p = precode(g)
    for start, length, e in ((50, 1, 1), (100, 7, 1), (200, 30, 2), (300, 8, 3)):
        sign = np.where(np.arange(length) % 2 == 0, e, -e)
        rx = p.copy()
        rx[start : start + length] = (rx[start : start + length] + sign) % 4
        wrong = np.flatnonzero(precode_inverse(rx) != g)
        assert list(wrong) == [start, start + length]
        # Without the precoder, the same burst corrupts every symbol in it.
        assert np.count_nonzero(rx != p) == length


def test_link_precoder_round_trip_and_ideal_channel_ber() -> None:
    # TX and RX in lockstep: no noise-free errors. A wrong sign on either side (1/(1-D)) breaks
    # this. On an ideal channel each slicer error is isolated, so Eq. 135-3 turns it into two
    # adjacent one-bit errors (to first order in SER). Errors come in pairs, so the binomial CI
    # applies to the pair count, which must match the unprecoded Gray BER.
    pulse, one = np.array([1.0]), np.array([1.0])
    for seed in range(8):  # several seeds: the symbol before the window varies (RX initial state)
        quiet = run_link(pulse, 0, one, 0, 0.0, 1.0, 60.0, 20_000, seed, 6, precoder=True)
        assert quiet.bit_errors == 0
    snr = 16.0
    r = run_link(pulse, 0, one, 0, 0.0, 1.0, snr, 2_000_000, 1, 2, precoder=True)
    lo, hi = clopper_pearson(r.bit_errors // 2, r.bits)
    assert r.bit_errors > 1000
    assert lo <= pam4_ber_awgn(snr) <= hi
