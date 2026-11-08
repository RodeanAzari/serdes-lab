"""Bit-exact TX -> channel -> noise -> ADC stream (model/tx.py): the Phase B RTL reference."""

import numpy as np
import pytest

from model import fixed as fx
from model import noise, pam4, prng, rs, tx

SEED = 0x1D2C3B4A
P = 4


@pytest.fixture(scope="module")
def tb() -> noise.Tables:
    return noise.build_tables(noise.NoiseCfg())


@pytest.fixture(scope="module")
def ch4() -> tuple[np.ndarray, int]:
    d = np.load("data/channels/kr_ch4_31p4db.npz")
    c, a0, a1 = int(d["cursor"]), int(d["n_pre"]), int(d["n_post"])
    return fx.channel_int(d["pulse"][c - a0 : c + a1 + 1], fx.FixedCfg()), a0


@pytest.mark.parametrize("precoder", [False, True])
def test_tx_round_trip(precoder: bool) -> None:
    """Undo every TX step independently: levels -> index -> (precoder inverse) -> bits -> RS
    symbols gives valid codewords whose message is the continuous PRBS31 stream."""
    out = tx.tx(3, SEED, precoder)
    n_sym = 3 * rs.N * rs.M // 2
    assert out.a.shape == (n_sym,) and set(np.unique(out.a)) <= {-3, -1, 1, 3}
    idx = (out.a + 3) // 2
    g = pam4.precode_inverse(idx, 0) if precoder else idx
    cw = rs.bits_to_symbols(pam4.gray_to_bits(g)).reshape(3, rs.N)
    assert (cw == out.cw).all()
    assert not rs.syndromes(cw).any()  # every codeword valid
    bits = rs.symbols_to_bits(cw[:, : rs.K])
    assert (bits == prng.prbs31(3 * rs.K * rs.M, SEED)).all()  # PRBS continuous, MSB first


def test_rs_symbol_alignment() -> None:
    """PAM4 symbols 5i..5i+4 carry RS symbol i (MSB first): symbol i = sum of 2-bit pairs."""
    out = tx.tx(1, SEED, False)
    pairs = pam4.gray_to_bits(out.gray).reshape(-1, 5, 2)
    sym = (pairs[:, :, 0].astype(np.int64) * 2 + pairs[:, :, 1]) @ (4 ** np.arange(4, -1, -1))
    assert (sym == out.cw[0]).all()


def test_precoder_state_carries_across_codewords() -> None:
    """Naive Eq. 135-1 loop over 4 codewords, P(-1) = 0 at reset only. A reset at a codeword
    boundary is invisible when P = 0 there, so require a boundary with nonzero state."""
    out = tx.tx(4, SEED, True)
    p, want = 0, []
    for g in out.gray.tolist():
        p = (g - p) % 4
        want.append(p)
    assert out.idx.tolist() == want
    per_cw = len(out.gray) // 4
    assert any(want[b * per_cw - 1] != 0 for b in (1, 2, 3))


def ref_words(n: int, seeds: list[prng.Seed258]) -> list[int]:
    """Pure-int: one generator per lane, word k from lane k % P after k // P + 1 steps."""
    st, w = list(seeds), []
    lanes: list[list[int]] = [[] for _ in seeds]
    for _ in range(-(-n // len(seeds))):
        for j, s in enumerate(st):
            st[j], o = prng.lfsr258_step(s)
            lanes[j].append(o)
    for k in range(n):
        w.append(lanes[k % len(seeds)][k // len(seeds)])
    return w


def test_pre_adc_matches_naive_sum(tb: noise.Tables, ch4: tuple[np.ndarray, int]) -> None:
    hq, cur = ch4
    a = tx.tx(1, SEED, False).a[:600]
    seeds = prng.lane_seeds(42, P)
    sigma_reg = round(49.4 * 32)
    y = tx.pre_adc(a, hq, cur, seeds, tb, sigma_reg)
    words = np.array(ref_words(len(a), seeds), dtype=np.uint64)
    nz = noise.noise(words, tb, sigma_reg)
    v = tx.valid(len(a), len(hq), cur)
    assert v.start == len(hq) - 1 - cur and v.stop == len(a) - cur
    for k in range(v.start, v.stop):
        s = sum(int(hq[j]) * int(a[k + cur - j]) for j in range(len(hq)))
        assert y[k] == max(-32767, min(32767, s + int(nz[k]))), k


def test_noise_alone_uses_word_k(tb: noise.Tables) -> None:
    """Zero channel: y is exactly the noise stream, word k <-> sample k (lane k mod P)."""
    seeds = prng.lane_seeds(9, P)
    y = tx.pre_adc(np.zeros(37, dtype=np.int64), np.zeros(3, dtype=np.int64), 1, seeds, tb, 4000)
    want = noise.noise(np.array(ref_words(37, seeds), dtype=np.uint64), tb, 4000)
    assert (y == want).all()
    assert np.count_nonzero(y) > 30


def test_pre_adc_saturates_not_wraps(tb: noise.Tables) -> None:
    hq = np.array([20000], dtype=np.int64)
    a = np.array([3, -3, 1, -1], dtype=np.int64)
    y = tx.pre_adc(a, hq, 0, prng.lane_seeds(1, P), tb, 0)  # sigma 0: no noise
    assert list(y) == [32767, -32767, 20000, -20000]


def test_front_end_adc() -> None:
    cfg = fx.FixedCfg()
    y = np.array([-32767, -32, -31, 31, 32, 4031, 4032, 32767], dtype=np.int64)
    assert list(tx.front_end(y, cfg)) == [-63, 0, 0, 0, 1, 63, 63, 63]


def test_bad_cursor(tb: noise.Tables) -> None:
    with pytest.raises(ValueError):
        tx.pre_adc(np.zeros(4, np.int64), np.ones(3, np.int64), 3, prng.lane_seeds(1, P), tb, 1)
