"""Link-model tests: mapping, DFE resolution, and that SNR/noise scaling matches theory."""

import numpy as np

from model.equalizer import mmse_ffe_dfe
from model.link import dfe1_decide, noise_sigma, run_link
from model.pam4 import LEVELS, bits_to_symbols, slice_idx, symbols_to_bits
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
