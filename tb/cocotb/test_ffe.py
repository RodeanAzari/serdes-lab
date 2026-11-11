"""ffe vs the model's causal FFE (model/rx.py ffe_causal), bit-exact.

z[m] = sat(round_half_up(sum_i c[i] x[m - i], shift), 10), checked for m >= N - 1.
Valid gaps: the history must shift only on valid_i, and valid_o must be valid_i delayed by 7.
"""

import os
from pathlib import Path

import cocotb
import numpy as np
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge
from tb_common import get_rng

from model import fixed as fx
from model import rx
from model.equalizer import mmse_ffe_dfe
from model.link import noise_sigma

P = int(os.environ.get("P", "4"))
N = int(os.environ.get("N", "16"))
X_W, C_W, Z_W, SH_W = 7, 10, 10, 4
LATENCY = 7
ROOT = Path(__file__).resolve().parents[2]
CMAX, CMIN = (1 << (C_W - 1)) - 1, -(1 << (C_W - 1))
XMAX = 63  # ADC output is symmetric (+-63); -64 is also driven to prove ACC_W
CFG = fx.FixedCfg()


def to_signed(v: int, w: int) -> int:
    return v - (1 << w) if v >> (w - 1) else v


def pack(vals: list[int], w: int) -> int:
    return sum((v & ((1 << w) - 1)) << (w * i) for i, v in enumerate(vals))


async def run(dut, rng, coefs: list[int], shift: int, x: list[int], valid: list[bool]) -> None:  # type: ignore[no-untyped-def]
    """One input word per entry of `valid` (samples from `x` on valid words, junk otherwise);
    check latency, then every defined output against model/rx.py ffe_causal."""
    assert len(coefs) == N and all(CMIN <= c <= CMAX for c in coefs)
    dut.coef_i.value = pack(coefs, C_W)
    dut.shift_i.value = shift
    dut.rst_i.value = 1
    dut.valid_i.value = 0
    for _ in range(3):
        await FallingEdge(dut.clk_i)
    dut.rst_i.value = 0
    vin: list[int] = []
    got: list[int] = []
    pos = 0
    for c in range(len(valid) + LATENCY):
        v = int(dut.valid_o.value)
        want_v = vin[c - LATENCY] if c >= LATENCY else 0
        assert v == want_v, f"clock {c}: valid_o = {v}, expected {want_v} (latency {LATENCY})"
        if v:
            zw = dut.z_o.value.to_unsigned()
            got += [to_signed((zw >> (Z_W * p)) & ((1 << Z_W) - 1), Z_W) for p in range(P)]
        on = c < len(valid) and valid[c]
        if on:
            word = x[pos : pos + P]
            pos += P
        else:
            word = [rng.randint(-64, 63) for _ in range(P)]  # junk: must be ignored
        dut.x_i.value = pack(word, X_W)
        dut.valid_i.value = int(on)
        vin.append(int(on))
        await FallingEdge(dut.clk_i)
    regs = fx.RxRegs(np.asarray(coefs, dtype=np.int64), shift, 0, 0)
    ref = rx.ffe_causal(np.asarray(x[:pos], dtype=np.int64), regs, CFG)
    assert len(got) == pos
    for m in range(N - 1, pos):
        assert got[m] == ref[m], f"symbol {m}: got {got[m]}, want {ref[m]} (shift {shift})"


def samples(rng, n_words: int) -> list[int]:  # type: ignore[no-untyped-def]
    return [rng.randint(-XMAX, XMAX) for _ in range(n_words * P)]


@cocotb.test()
async def test_random(dut) -> None:  # type: ignore[no-untyped-def]
    """Full-range random taps (extremes included), every shift 0..15, random valid gaps."""
    rng = get_rng("test_ffe")
    cocotb.start_soon(Clock(dut.clk_i, 8, unit="ns").start())
    for trial in range(16):
        coefs = [rng.choice([CMIN, CMAX, rng.randint(CMIN, CMAX)]) for _ in range(N)]
        p_valid = (1.0, 0.7, 0.3)[trial % 3]
        n = 150
        valid = [rng.random() < p_valid for _ in range(n)]
        await run(dut, rng, coefs, trial, samples(rng, sum(valid)), valid)


@cocotb.test()
async def test_impulse(dut) -> None:  # type: ignore[no-untyped-def]
    """One nonzero tap at each position, shift 0: the output is the input delayed by i, scaled
    (alignment and tap order)."""
    rng = get_rng("test_ffe_impulse")
    cocotb.start_soon(Clock(dut.clk_i, 8, unit="ns").start())
    for i in range(N):
        coefs = [0] * N
        coefs[i] = rng.choice([1, -1, 5])
        n = 3 * (N // P + 2)
        await run(dut, rng, coefs, 0, samples(rng, n), [True] * n)


@cocotb.test()
async def test_worst_case(dut) -> None:  # type: ignore[no-untyped-def]
    """Largest |acc| = 64 * 512 * N (x = -64, c = -512) and its negative, at shift 0 (saturates)
    and at the largest shifts, where acc + 2^(shift-1) would wrap ACC_W: proves the widths."""
    rng = get_rng("test_ffe_worst")
    cocotb.start_soon(Clock(dut.clk_i, 8, unit="ns").start())
    n = N // P + 4
    for c in (CMIN, CMAX):
        for xv in (-64, 63):
            for shift in (0, 10, 14, 15):
                await run(dut, rng, [c] * N, shift, [xv] * (n * P), [True] * n)


@cocotb.test()
async def test_rounding_ties(dut) -> None:  # type: ignore[no-untyped-def]
    """acc = +-k * 2^(s-1) for odd k: exact ties, which must round toward +inf (half up)."""
    rng = get_rng("test_ffe_ties")
    cocotb.start_soon(Clock(dut.clk_i, 8, unit="ns").start())
    coefs = [1] + [0] * (N - 1)  # acc = x[m]
    n = 40
    for shift in (1, 2, 3):
        half = 1 << (shift - 1)  # odd k * half is an exact tie; |x| <= 63 without clamping
        x = [rng.choice([-1, 1]) * rng.randrange(1, 64 // half, 2) * half for _ in range(n * P)]
        await run(dut, rng, coefs, shift, x, [True] * n)


@cocotb.test()
async def test_real_channels(dut) -> None:  # type: ignore[no-untyped-def]
    """MMSE taps and shift for the emulated channels (model/fixed.py rx_regs), real-ish input."""
    rng = get_rng("test_ffe_ch")
    cocotb.start_soon(Clock(dut.clk_i, 8, unit="ns").start())
    if N != 16:
        dut._log.warning(f"N = {N}: real-channel taps are 16 long, not run")
        return
    for name in ("kr_ch2_19p3db", "kr_ch4_31p4db"):
        d = np.load(ROOT / "data" / "channels" / f"{name}.npz")
        c, a0, a1 = int(d["cursor"]), int(d["n_pre"]), int(d["n_post"])
        hq = fx.channel_int(d["pulse"][c - a0 : c + a1 + 1], CFG)
        h = hq.astype(np.float64)
        eq = mmse_ffe_dfe(h, a0, N, 4, 1, noise_sigma(h, 25.0) ** 2)
        regs = fx.rx_regs(hq, a0, eq.taps, 4, CFG)
        a = 2 * np.array([rng.randrange(4) for _ in range(400 * P)]) - 3
        x = fx.adc(np.convolve(a, hq)[: len(a)], CFG.frac, CFG.adc_bits).tolist()
        await run(dut, rng, regs.coefs.tolist(), regs.out_shift, x, [True] * 400)
