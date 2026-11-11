"""RX stream in the hardware's causal frame (model/rx.py): the Phase C RTL reference."""

import numpy as np
import pytest

from model import fixed as fx
from model import noise, prng, rx, tx
from model.equalizer import mmse_ffe_dfe
from model.link import noise_sigma

SEED = 0x2468ACE1
N, N_PRE = 16, 4
CFG = fx.FixedCfg()
CHANNELS = ["kr_ch2_19p3db", "kr_ch4_31p4db"]


def channel(name: str) -> tuple[np.ndarray, int, fx.RxRegs]:
    d = np.load(f"data/channels/{name}.npz")
    c, a0, a1 = int(d["cursor"]), int(d["n_pre"]), int(d["n_post"])
    hq = fx.channel_int(d["pulse"][c - a0 : c + a1 + 1], CFG)
    h = hq.astype(np.float64)
    eq = mmse_ffe_dfe(h, a0, N, N_PRE, 1, noise_sigma(h, 30.0) ** 2)
    return hq, a0, fx.rx_regs(hq, a0, eq.taps, N_PRE, CFG)


def test_ffe_causal_is_the_reference_ffe_delayed_by_n_pre() -> None:
    # ffe_out is the path validated against the float receiver (test_fixed.py); the causal
    # hardware frame must be exactly that stream, n_pre symbols later.
    _, _, regs = channel("kr_ch4_31p4db")
    x = np.random.default_rng(1).integers(-63, 64, 2000)
    zc, zr = rx.ffe_causal(x, regs, CFG), fx.ffe_out(x, regs, N_PRE, CFG)
    m = np.arange(N - 1, len(x))
    assert np.array_equal(zc[m], zr[m - N_PRE])


def test_ffe_causal_naive_sum_with_saturation() -> None:
    # Full-scale taps and inputs drive z far beyond 10 bits: both rails must clip symmetrically.
    rng = np.random.default_rng(2)
    regs = fx.RxRegs(rng.choice([-511, 511], N), 1, 0, 100)
    x = rng.choice([-63, 63], 3000)
    z = rx.ffe_causal(x, regs, CFG)
    for m in range(N - 1, len(x)):
        acc = sum(int(regs.coefs[i]) * int(x[m - i]) for i in range(N))
        assert z[m] == max(-511, min(511, (acc + 1) >> 1))
    assert (z == 511).any() and (z == -511).any()


@pytest.mark.parametrize("name", CHANNELS)
@pytest.mark.parametrize("precoder", [False, True])
def test_noiseless_link_returns_the_tx_gray_stream(name: str, precoder: bool) -> None:
    """TX -> channel (sigma 0) -> ADC -> FFE -> DFE -> demap gives back every TX Gray symbol,
    m - cursor - n_pre symbols back. Any off-by-one in either frame breaks it everywhere."""
    hq, cur, regs = channel(name)
    t = tx.tx(2, SEED, precoder)
    y = tx.pre_adc(t.a, hq, cur, prng.lane_seeds(7, 4), noise.build_tables(noise.NoiseCfg()), 0)
    v = tx.valid(len(t.a), len(hq), cur)
    x_hw = tx.front_end(y, CFG)[v]  # hardware symbols m = len(hq) - 1, ...
    k0 = v.start + N - 1  # model frame index of the first RX output
    out = rx.rx(x_hw, regs, CFG, precoder, d_init=int(t.idx[k0 - N_PRE - 1]),
                p_init=int(t.idx[k0 - N_PRE - 1]))  # fmt: skip
    want = t.gray[k0 - N_PRE : k0 - N_PRE + len(out.gray)]
    assert len(out.gray) > 5000
    assert np.array_equal(out.gray, want)
    assert np.array_equal(out.idx, t.idx[k0 - N_PRE : k0 - N_PRE + len(out.idx)])


def test_wrong_start_state_costs_only_a_short_burst() -> None:
    # d_init / p_init are reset values in RTL. A wrong guess starts a DFE error burst even
    # without noise (Ch4: 2b = 90 > h0 = 62), measured <= 3 symbols, +1 Gray symbol from the
    # precoder inverse; after it the stream must be exact.
    hq, cur, regs = channel("kr_ch4_31p4db")
    t = tx.tx(1, SEED, True)
    y = tx.pre_adc(t.a, hq, cur, prng.lane_seeds(7, 4), noise.build_tables(noise.NoiseCfg()), 0)
    v = tx.valid(len(t.a), len(hq), cur)
    k0 = v.start + N - 1
    want = t.gray[k0 - N_PRE :]
    for d0 in range(4):
        out = rx.rx(tx.front_end(y, CFG)[v], regs, CFG, True, d_init=d0, p_init=(d0 + 1) % 4)
        assert np.array_equal(out.gray[8:], want[8 : len(out.gray)])
