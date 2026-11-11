"""link_core vs the bit-exact model, identical error counts on fixed seeds (buildplan §9):
model tx -> pre_adc -> front_end -> rx.rx(start) -> rx.count_errors (ADR 0011 frame).

Noiseless runs must count zero errors after the holdoff: that checks the TX/RX alignment (K,
M0) independently of the model's own frame. Noisy runs (Ch4 and Ch2, precoder off/on) must
match the model's bit, bit-error and symbol-error counts exactly, with hundreds of errors and
DFE error propagation in the stream.
"""

import math
import os
from pathlib import Path

import cocotb
import numpy as np
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge
from tb_common import get_rng

from model import fixed as fx
from model import noise, prng, rx, tx
from model.equalizer import mmse_ffe_dfe
from model.link import noise_sigma

P = int(os.environ.get("P", "4"))
L, N, N_PRE, TAP_W, C_W = 16, 16, 4, 11, 10
M0 = P * math.ceil((L + N - 2) / P)
ROOT = Path(__file__).resolve().parents[2]
TB = noise.build_tables(noise.NoiseCfg())  # ~20 s
CFG = fx.FixedCfg()


def channel(name: str) -> tuple[list[int], int, fx.RxRegs]:
    d = np.load(ROOT / f"data/channels/{name}.npz")
    c, a0, a1 = int(d["cursor"]), int(d["n_pre"]), int(d["n_post"])
    hq = fx.channel_int(d["pulse"][c - a0 : c + a1 + 1], CFG)
    h = hq.astype(np.float64)
    eq = mmse_ffe_dfe(h, a0, N, N_PRE, 1, noise_sigma(h, 30.0) ** 2)
    return hq.tolist(), a0, fx.rx_regs(hq, a0, eq.taps, N_PRE, CFG)


def pack(vals: list[int], w: int) -> int:
    return sum((v & ((1 << w) - 1)) << (w * i) for i, v in enumerate(vals))


async def run(dut, rng, name: str, precoder: bool, sigma: int, holdoff: int,  # type: ignore[no-untyped-def]
              n_cw: int) -> rx.ErrCount:  # fmt: skip
    hq, cursor, regs = channel(name)
    k = cursor + N_PRE
    prbs_seed = rng.getrandbits(31) or 1
    seeds = prng.lane_seeds(rng.getrandbits(64), P)

    t = tx.tx(n_cw, prbs_seed, precoder)
    y = tx.pre_adc(t.a, np.array(hq, dtype=np.int64), cursor, seeds, TB, sigma)
    x_hw = tx.front_end(y, CFG)[tx.valid(len(t.a), L, cursor)]  # hardware m = L - 1, ...
    out = rx.rx(x_hw, regs, CFG, precoder, d_init=0, p_init=0, start=M0 - (L - 1))
    n_rx = len(out.gray) // P  # RX words the model covers

    dut.prbs_seed_i.value = prbs_seed
    dut.precode_i.value = int(precoder)
    dut.taps_i.value = pack(hq + [0] * (L - len(hq)), TAP_W)
    dut.noise_seed_i.value = sum(
        sum(w << (64 * c) for c, w in enumerate(s)) << (320 * i) for i, s in enumerate(seeds)
    )
    dut.sigma_i.value = sigma
    dut.coef_i.value = pack([int(c) for c in regs.coefs], C_W)
    dut.shift_i.value = regs.out_shift
    dut.b_i.value = regs.dfe_b & ((1 << 10) - 1)
    dut.t2_i.value = regs.t2
    dut.lag_i.value = k
    dut.holdoff_i.value = holdoff
    dut.rst_i.value = 1
    for _ in range(3):
        await FallingEdge(dut.clk_i)
    dut.rst_i.value = 0

    seen = cyc = 0
    while seen < n_rx:  # the counters include an RX word 2 clocks after it is visible here
        await FallingEdge(dut.clk_i)
        cyc += 1
        assert cyc < len(t.a) // P + 200, "timeout: RX words stopped"
        seen += int(dut.u_rx.valid_o.value)
    for _ in range(2):
        await FallingEdge(dut.clk_i)
    got = rx.ErrCount(int(dut.bits_o.value), int(dut.bit_err_o.value), int(dut.sym_err_o.value))
    want = rx.count_errors(out.gray[: n_rx * P], t.gray, M0 - k, holdoff * P)
    assert int(dut.err_o.value) == 0, "ber_check FIFO over/underflow"
    assert int(dut.cfg_err_o.value) == 0
    assert got == want, f"{name} precoder {precoder} sigma {sigma}: got {got}, model {want}"
    dut._log.info(f"{name} pre {precoder} sigma {sigma}: {got}")
    return got


@cocotb.test()
async def test_noiseless_link_is_error_free(dut) -> None:  # type: ignore[no-untyped-def]
    rng = get_rng("test_link_core_clean")
    cocotb.start_soon(Clock(dut.clk_i, 8, unit="ns").start())
    for name in ("kr_ch4_31p4db", "kr_ch2_19p3db"):
        for pre in (False, True):
            c = await run(dut, rng, name, pre, 0, 2, 2)
            # 2 codewords = 10880 TX bits, less the warm-up and the model's end edge
            assert c.bit_errors == 0 and c.sym_errors == 0 and c.bits > 10000, c


@cocotb.test()
async def test_noisy_link_counts_match_the_model(dut) -> None:  # type: ignore[no-untyped-def]
    """sigma ~3x the 1e-12 operating point: BER ~1e-2, so hundreds of errors per run."""
    rng = get_rng("test_link_core_noisy")
    cocotb.start_soon(Clock(dut.clk_i, 8, unit="ns").start())
    for name, sigma, pre, holdoff in (("kr_ch4_31p4db", 4800, False, 0),
                                      ("kr_ch4_31p4db", 4800, True, 3),
                                      ("kr_ch2_19p3db", 7000, True, 1)):  # fmt: skip
        c = await run(dut, rng, name, pre, sigma, holdoff, 3)
        assert c.sym_errors > 100, f"only {c.sym_errors} symbol errors: run is not exercising"


@cocotb.test()
async def test_lag_beyond_m0_flags_config_error(dut) -> None:  # type: ignore[no-untyped-def]
    cocotb.start_soon(Clock(dut.clk_i, 8, unit="ns").start())
    for lag, want in ((M0, 0), (M0 + 1, 1)):
        dut.lag_i.value = lag
        await FallingEdge(dut.clk_i)
        assert int(dut.cfg_err_o.value) == want, lag
