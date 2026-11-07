"""Fixed-point receiver blocks (model/fixed.py): the bit-exact reference the RTL must match."""

import numpy as np

from model import fixed as fx
from model.equalizer import mmse_ffe_dfe
from model.link import dfe1_decide, noise_sigma
from model.pam4 import bits_to_symbols, slice_idx


def test_round_shift_is_round_half_up() -> None:
    # RTL does (x + 2^(s-1)) >>> s. Ties go toward +inf, including negatives (-1.5 -> -1).
    x = np.array([-7, -6, -5, -3, -2, -1, 0, 1, 2, 3, 5, 6, 7], dtype=np.int64)
    assert list(fx.round_shift(x, 1)) == [-3, -3, -2, -1, -1, 0, 0, 1, 1, 2, 3, 3, 4]
    rng = np.random.default_rng(1)
    y = rng.integers(-(1 << 40), 1 << 40, 100_000)
    for s in (1, 3, 9):
        assert np.array_equal(fx.round_shift(y, s), np.floor(y / 2**s + 0.5).astype(np.int64))
    assert np.array_equal(fx.round_shift(y, 0), y)


def test_saturation_is_symmetric() -> None:
    # Asymmetric two's-complement clipping (-64..63) would bias the -3 level vs +3.
    x = np.arange(-200, 201, dtype=np.int64)
    s = fx.sat(x, 7)
    assert s.min() == -63 and s.max() == 63
    assert np.array_equal(s, -fx.sat(-x, 7))
    assert np.array_equal(s[np.abs(x) <= 63], x[np.abs(x) <= 63])  # in range: untouched


def test_adc_rounds_then_saturates() -> None:
    y = np.array([-10_000, -96, -95, -32, 31, 32, 95, 96, 10_000], dtype=np.int64)  # frac = 6
    assert list(fx.adc(y, 6, 7)) == [-63, -1, -1, 0, 0, 1, 1, 2, 63]


def test_slicer_ties_and_float_equivalence() -> None:
    t2 = 40
    v = np.array([-41, -40, -39, -1, 0, 1, 39, 40, 41], dtype=np.int64)
    assert list(fx.slice_int(v, t2)) == [0, 1, 1, 1, 2, 2, 2, 3, 3]
    rng = np.random.default_rng(2)
    w = rng.integers(-200, 200, 10_000)
    assert np.array_equal(fx.slice_int(w, t2), slice_idx(w.astype(np.float64), t2 / 2))


def test_integer_dfe_matches_fast_float_dfe() -> None:
    # The scripts run the fast float DFE on integer z; it must be exact for integer inputs.
    rng = np.random.default_rng(3)
    z = rng.integers(-500, 500, 20_000)
    for b in (-17, 0, 23):
        ref = fx.dfe1_int(z, b, 120, 2)
        assert np.array_equal(dfe1_decide(z.astype(np.float64), float(b), 60.0, 2), ref)


def test_ffe_acc_alignment_matches_float_link() -> None:
    # Same indexing as model/link.py: z[k] = sum_i c[i] x[k + n_pre - i].
    rng = np.random.default_rng(4)
    x = rng.integers(-63, 64, 500)
    c = rng.integers(-511, 512, 16)
    acc = fx.ffe_acc(x, c, 4)
    k = 100
    assert acc[k] == sum(int(c[i]) * int(x[k + 4 - i]) for i in range(16))


def test_quantize_coefs_uses_full_range() -> None:
    w = np.array([0.1, -0.8, 0.35, 0.02])
    q, scale = fx.quantize_coefs(w, 10)
    assert np.max(np.abs(q)) == 511
    assert np.max(np.abs(q / scale - w)) <= 0.5 / scale + 1e-12


def _paired(cfg: fx.FixedCfg, snr_db: float = 26.0, n: int = 200_000) -> tuple[float, float]:
    """Slicer SNR (dB) of float vs. fixed receiver on identical Ch4 samples, ideal DFE."""
    d = np.load("data/channels/kr_ch4_31p4db.npz")
    c, a0, a1 = int(d["cursor"]), int(d["n_pre"]), int(d["n_post"])
    pulse = d["pulse"][c - a0 : c + a1 + 1]
    hq = fx.channel_int(pulse, cfg)
    h = hq.astype(np.float64)
    sigma = noise_sigma(h, snr_db)
    rng = np.random.default_rng(5)
    a = bits_to_symbols(rng.integers(0, 2, 2 * n, dtype=np.uint8))
    s = np.convolve(a, hq)[a0 : a0 + n]
    noise = np.random.default_rng(6).normal(0.0, sigma, n)
    eq = mmse_ffe_dfe(h, a0, 16, 4, 1, sigma**2)
    regs = fx.rx_regs(hq, a0, eq.taps, 4, cfg)
    g = 40
    an, ap = a[g:-g], a[g - 1 : -g - 1]
    zf = np.convolve(s + noise, eq.taps)[4 : 4 + n][g:-g]
    zi = fx.ffe_out(fx.adc(s + np.round(noise).astype(np.int64), cfg.frac, cfg.adc_bits),
                    regs, 4, cfg)[g:-g]  # fmt: skip
    ef = (zf - eq.dfe[0] * ap) / eq.h0 - an
    ei = (zi - regs.dfe_b * ap) / (regs.t2 / 2) - an
    return 10 * np.log10(5 / np.mean(ef**2)), 10 * np.log10(5 / np.mean(ei**2))


def test_wide_fixed_point_matches_float() -> None:
    # With generous widths the integer chain must reproduce the float receiver: any
    # misalignment (cursor, DFE tap index, shift, threshold scale) shows as a large penalty.
    f, i = _paired(fx.FixedCfg(adc_bits=14, clip=4.0, frac=8, coef_bits=18, out_bits=20))
    assert abs(f - i) < 0.02


def test_chosen_config_penalty_is_bounded_and_ordered() -> None:
    # ADR 0004: 7-bit ADC costs ~0.4-0.6 dB on Ch4 at high SNR, 6 bits clearly more.
    # Guards the measured trade-off from silently changing.
    f7, i7 = _paired(fx.FixedCfg())
    f6, i6 = _paired(fx.FixedCfg(adc_bits=6))
    assert 0.1 < f7 - i7 < 1.0
    assert (f6 - i6) > (f7 - i7) + 0.5


def test_rx_regs_place_outer_level_in_upper_half_range() -> None:
    d = np.load("data/channels/kr_ch2_19p3db.npz")
    c, a0, a1 = int(d["cursor"]), int(d["n_pre"]), int(d["n_post"])
    pulse = d["pulse"][c - a0 : c + a1 + 1]
    cfg = fx.FixedCfg()
    hq = fx.channel_int(pulse, cfg)
    eq = mmse_ffe_dfe(hq.astype(np.float64), a0, 16, 4, 1, 1.0)
    r = fx.rx_regs(hq, a0, eq.taps, 4, cfg)
    outer = 1.5 * r.t2  # 3 * h0
    fs = (1 << (cfg.out_bits - 1)) - 1
    assert fs / 4 < outer <= fs / 2 + 1
