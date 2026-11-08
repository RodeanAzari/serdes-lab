"""channel_fir vs the model's channel s = conv(a, hq) (model/tx.py pre_adc), bit-exact.

Causal output m = sum_j hq[j] a[m - j], checked for m >= L - 1 (header of channel_fir.sv).
Valid gaps: the history must shift only on valid_i, and valid_o must be valid_i delayed by 3.
"""

import os
from pathlib import Path

import cocotb
import numpy as np
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge
from tb_common import get_rng

from model import fixed as fx

P = int(os.environ.get("P", "4"))
L = int(os.environ.get("L", "16"))
TAP_W = 11
S_W = TAP_W + 2 + (L - 1).bit_length()  # TAP_W + 2 + clog2(L)
LATENCY = 3
ROOT = Path(__file__).resolve().parents[2]
TMAX, TMIN = (1 << (TAP_W - 1)) - 1, -(1 << (TAP_W - 1))


def to_signed(v: int, w: int) -> int:
    return v - (1 << w) if v >> (w - 1) else v


async def run(dut, rng, taps: list[int], idx: list[int], valid: list[bool]) -> None:  # type: ignore[no-untyped-def]
    """Drive one input word per entry of `valid` (symbols from `idx`, in order, on valid words;
    junk otherwise); check latency, then every defined output against the convolution."""
    assert len(taps) == L and all(TMIN <= t <= TMAX for t in taps)
    dut.taps_i.value = sum((t & ((1 << TAP_W) - 1)) << (TAP_W * j) for j, t in enumerate(taps))
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
            sw = dut.s_o.value.to_unsigned()
            got += [to_signed((sw >> (S_W * p)) & ((1 << S_W) - 1), S_W) for p in range(P)]
        on = c < len(valid) and valid[c]
        if on:
            word = idx[pos : pos + P]
            pos += P
        else:
            word = [rng.randrange(4) for _ in range(P)]  # junk: must be ignored
        dut.idx_i.value = sum(s << (2 * p) for p, s in enumerate(word))
        dut.valid_i.value = int(on)
        vin.append(int(on))
        await FallingEdge(dut.clk_i)
    a = 2 * np.asarray(idx[:pos], dtype=np.int64) - 3
    ref = np.convolve(a, np.asarray(taps, dtype=np.int64))[:pos]
    assert len(got) == pos
    for m in range(L - 1, pos):
        assert got[m] == ref[m], f"symbol {m}: got {got[m]}, want {ref[m]} (taps {taps})"


def words(rng, n_words: int) -> list[int]:  # type: ignore[no-untyped-def]
    return [rng.randrange(4) for _ in range(n_words * P)]


@cocotb.test()
async def test_random(dut) -> None:  # type: ignore[no-untyped-def]
    """Full-range random taps (extremes included), random symbols, random valid gaps."""
    rng = get_rng("test_channel_fir")
    cocotb.start_soon(Clock(dut.clk_i, 8, unit="ns").start())
    for trial in range(6):
        taps = [rng.choice([TMIN, TMAX, rng.randint(TMIN, TMAX)]) for _ in range(L)]
        p_valid = (1.0, 0.7, 0.3)[trial % 3]
        n = 200
        valid = [rng.random() < p_valid for _ in range(n)]
        await run(dut, rng, taps, words(rng, sum(valid)), valid)


@cocotb.test()
async def test_impulse(dut) -> None:  # type: ignore[no-untyped-def]
    """Delta at each tap position: the output is the input delayed by j and scaled (alignment)."""
    rng = get_rng("test_channel_fir_impulse")
    cocotb.start_soon(Clock(dut.clk_i, 8, unit="ns").start())
    for j in range(L):
        taps = [0] * L
        taps[j] = rng.choice([1, -1, 37, TMIN])
        n = 3 * (L // P + 2)
        await run(dut, rng, taps, words(rng, n), [True] * n)


@cocotb.test()
async def test_worst_case(dut) -> None:  # type: ignore[no-untyped-def]
    """Largest |s|: every tap at -2^(TAP_W-1) or +max with constant symbols -3 / +3. Proves S_W."""
    rng = get_rng("test_channel_fir_worst")
    cocotb.start_soon(Clock(dut.clk_i, 8, unit="ns").start())
    n = L // P + 4
    for t in (TMIN, TMAX):
        for s in (0, 3):
            await run(dut, rng, [t] * L, [s] * (n * P), [True] * n)
            assert 3 * L * abs(t) < (1 << (S_W - 1))


@cocotb.test()
async def test_real_channels(dut) -> None:  # type: ignore[no-untyped-def]
    """The emulated channels' integer taps (model/fixed.py channel_int, 99.9% window), padded."""
    rng = get_rng("test_channel_fir_ch")
    cocotb.start_soon(Clock(dut.clk_i, 8, unit="ns").start())
    for name in ("kr_ch2_19p3db", "kr_ch4_31p4db"):
        d = np.load(ROOT / "data" / "channels" / f"{name}.npz")
        c, a0, a1 = int(d["cursor"]), int(d["n_pre"]), int(d["n_post"])
        hq = fx.channel_int(d["pulse"][c - a0 : c + a1 + 1], fx.FixedCfg()).tolist()
        if len(hq) > L:
            dut._log.warning(f"{name}: {len(hq)} taps > L = {L}, not run at this L")
            continue
        n = 300
        await run(dut, rng, hq + [0] * (L - len(hq)), words(rng, n), [True] * n)
