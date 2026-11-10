"""channel_top vs model/tx.py: tx -> pre_adc -> front_end, bit-exact (ADR 0008 alignment).

Output symbol m (from the first valid output) is model symbol k = m - cursor; checked for
L - 1 <= m < n_sym. The internal pre-ADC word y is checked too: the ADC's 7 b saturation would
hide a missing or wrapping 16 b saturation. Latency TX word -> x_o must be 16 clocks.

Runs: real Ch4 and Ch2 taps at their 1e-12 operating sigmas, precoder off and on; sigma 0
(pure ISI); full-scale taps (|s| up to 3 * 1023 * L) with maximum sigma over more codewords,
which drives y into 16 b saturation on both sides.
"""

import os
from pathlib import Path

import cocotb
import numpy as np
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge
from tb_common import get_rng

from model import fixed as fx
from model import noise, prng, tx

P = int(os.environ.get("P", "4"))
L, TAP_W, LATENCY = 16, 11, 16
ROOT = Path(__file__).resolve().parents[2]
TB = noise.build_tables(noise.NoiseCfg())  # ~20 s
CFG = fx.FixedCfg()
N_CW = 2
N_CW_SAT = 40  # |s + n| > 2^15 is a ~3.3 sigma event even at full-scale taps


def channel(name: str) -> tuple[list[int], int]:
    d = np.load(ROOT / f"data/channels/{name}.npz")
    c, a0, a1 = int(d["cursor"]), int(d["n_pre"]), int(d["n_post"])
    return fx.channel_int(d["pulse"][c - a0 : c + a1 + 1], CFG).tolist(), a0


def to_signed(v: int, w: int) -> int:
    return v - (1 << w) if v >> (w - 1) else v


def lanes(raw: int, w: int) -> list[int]:
    return [to_signed((raw >> (w * i)) & ((1 << w) - 1), w) for i in range(P)]


async def run(  # type: ignore[no-untyped-def]
    dut, rng, hq: list[int], cursor: int, precoder: bool, sigma: int, n_cw: int = N_CW
) -> dict[str, int]:
    assert len(hq) <= L
    prbs_seed = rng.getrandbits(31) or 1
    seeds = prng.lane_seeds(rng.getrandbits(64), P)
    out = tx.tx(n_cw, prbs_seed, precoder)
    n_sym = len(out.a)
    y_mod = tx.pre_adc(out.a, np.array(hq, dtype=np.int64), cursor, seeds, TB, sigma)
    x_mod = tx.front_end(y_mod, CFG)

    taps = hq + [0] * (L - len(hq))
    dut.taps_i.value = sum((t & ((1 << TAP_W) - 1)) << (TAP_W * j) for j, t in enumerate(taps))
    dut.noise_seed_i.value = sum(
        sum(w << (64 * c) for c, w in enumerate(s)) << (320 * i) for i, s in enumerate(seeds)
    )
    dut.prbs_seed_i.value = prbs_seed
    dut.precode_i.value = int(precoder)
    dut.sigma_i.value = sigma
    dut.rst_i.value = 1
    for _ in range(3):
        await FallingEdge(dut.clk_i)
    dut.rst_i.value = 0

    cyc, tx_first, x_first = 0, None, None
    my = mx = 0  # next output symbol index for y and x
    st = {"checked": 0, "y_sat+": 0, "y_sat-": 0, "x_sat": 0}
    while mx < n_sym:
        await FallingEdge(dut.clk_i)
        cyc += 1
        assert cyc < n_sym // P + 100, "timeout: outputs stopped"
        if tx_first is None and int(dut.u_tx.valid_o.value):
            tx_first = cyc
        if my < n_sym and int(dut.y_valid_q.value):
            ys = lanes(int(dut.y_q.value), 16)
            for i, yv in enumerate(ys):
                m = my + i
                if L - 1 <= m < n_sym:
                    want = y_mod[m - cursor]
                    assert yv == want, f"y: symbol m={m} lane {i}: {yv} != {want}"
                    st["y_sat+"] += yv == (1 << 15) - 1
                    st["y_sat-"] += yv == -((1 << 15) - 1)
            my += P
        if int(dut.valid_o.value):
            if x_first is None:
                x_first = cyc
            else:
                assert cyc - x_first == mx // P, "valid_o gap after start"
            xs = lanes(int(dut.x_o.value), 7)
            for i, xv in enumerate(xs):
                m = mx + i
                if L - 1 <= m < n_sym:
                    want = x_mod[m - cursor]
                    assert xv == want, f"x: symbol m={m} lane {i}: {xv} != {want}"
                    st["checked"] += 1
                    st["x_sat"] += abs(xv) == 63
            mx += P
    assert tx_first is not None and x_first is not None
    assert x_first - tx_first == LATENCY, f"latency {x_first - tx_first}, expected {LATENCY}"
    return st


@cocotb.test()
async def test_matches_model(dut) -> None:  # type: ignore[no-untyped-def]
    rng = get_rng("test_channel_top")
    dut.rst_i.value = 1
    cocotb.start_soon(Clock(dut.clk_i, 8, unit="ns").start())
    ch4, ch2 = channel("kr_ch4_31p4db"), channel("kr_ch2_19p3db")
    tmax = (1 << (TAP_W - 1)) - 1
    cases = [
        ("ch4", *ch4, False, round(49.4 * 32)),
        ("ch4 precoded", *ch4, True, round(49.4 * 32)),
        ("ch2 precoded", *ch2, True, round(76.4 * 32)),
        ("ch4 no noise", *ch4, False, 0),
        ("full-scale taps, max sigma", [tmax] * L, 0, False, (1 << 17) - 1),
    ]
    for name, hq, cur, pre, sigma in cases:
        sat = name.startswith("full-scale")
        st = await run(dut, rng, hq, cur, pre, sigma, N_CW_SAT if sat else N_CW)
        dut._log.info(f"{name}: {st}")
        assert st["checked"] > N_CW * 2720 - L
        if sat:
            assert min(st["y_sat+"], st["y_sat-"]) >= 10, "16 b saturation not exercised"
