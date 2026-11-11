"""dfe_slicer vs the sequential 1-tap DFE (model/fixed.py dfe1_int), bit-exact.

d[m] = slice(z[m] - b * level(d[m-1])), d[-1] = D_INIT after every reset; checked for every
symbol. Valid gaps: the loop must advance only on valid words; valid_o = valid_i delayed by 3.
"""

import os

import cocotb
import numpy as np
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge
from tb_common import get_rng

from model import fixed as fx

P = int(os.environ.get("P", "4"))
D_INIT = int(os.environ.get("D_INIT", "0"))
Z_W, B_W, T_W = 10, 10, 10
LATENCY = 3
ZMIN, ZMAX = -(1 << (Z_W - 1)), (1 << (Z_W - 1)) - 1
BMIN, BMAX = -(1 << (B_W - 1)), (1 << (B_W - 1)) - 1
TMAX = (1 << T_W) - 1


def pack(vals: list[int], w: int) -> int:
    return sum((v & ((1 << w) - 1)) << (w * i) for i, v in enumerate(vals))


async def run(dut, rng, b: int, t2: int, z: list[int], valid: list[bool]) -> None:  # type: ignore[no-untyped-def]
    """Reset, then one input word per entry of `valid` (z on valid words, junk otherwise);
    check latency and every decision against dfe1_int(z, b, t2, D_INIT)."""
    dut.b_i.value = b & ((1 << B_W) - 1)
    dut.t2_i.value = t2
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
            dw = dut.d_o.value.to_unsigned()
            got += [(dw >> (2 * p)) & 3 for p in range(P)]
        on = c < len(valid) and valid[c]
        if on:
            word = z[pos : pos + P]
            pos += P
        else:
            word = [rng.randint(ZMIN, ZMAX) for _ in range(P)]  # junk: must be ignored
        dut.z_i.value = pack(word, Z_W)
        dut.valid_i.value = int(on)
        vin.append(int(on))
        await FallingEdge(dut.clk_i)
    ref = fx.dfe1_int(np.asarray(z[:pos], dtype=np.int64), b, t2, D_INIT).tolist()
    assert len(got) == pos
    for m in range(pos):
        assert got[m] == ref[m], f"symbol {m}: got {got[m]}, want {ref[m]} (b {b}, t2 {t2})"


@cocotb.test()
async def test_random(dut) -> None:  # type: ignore[no-untyped-def]
    """Full-range z, b (extremes included) and t2 (0 and max included), random valid gaps.
    Random z exercises every (previous, next) decision pair through the loop."""
    rng = get_rng("test_dfe_slicer")
    cocotb.start_soon(Clock(dut.clk_i, 8, unit="ns").start())
    for trial in range(18):
        b = rng.choice([BMIN, BMAX, 0, rng.randint(BMIN, BMAX)])
        t2 = rng.choice([0, TMAX, rng.randint(0, TMAX)])
        n = 120
        valid = [rng.random() < (1.0, 0.6, 0.2)[trial % 3] for _ in range(n)]
        z = [rng.choice([ZMIN, ZMAX, rng.randint(ZMIN, ZMAX)]) for _ in range(sum(valid) * P)]
        await run(dut, rng, b, t2, z, valid)


@cocotb.test()
async def test_ties(dut) -> None:  # type: ignore[no-untyped-def]
    """z placed so that z - b * level(prev) lands exactly on -t2, 0 or +t2 for some previous
    level: ties must go up (>=), in all four candidate paths."""
    rng = get_rng("test_dfe_slicer_ties")
    cocotb.start_soon(Clock(dut.clk_i, 8, unit="ns").start())
    for b, t2 in ((37, 158), (45, 124), (-20, 100), (0, 1)):
        n = 100
        z = []
        for _ in range(n * P):
            lv = rng.choice([-3, -1, 1, 3])
            z.append(max(ZMIN, min(ZMAX, rng.choice([-t2, 0, t2]) + b * lv)))
        await run(dut, rng, b, t2, z, [True] * n)


@cocotb.test()
async def test_noisy_pam4(dut) -> None:  # type: ignore[no-untyped-def]
    """Realistic z: PAM4 with post-cursor ISI b and Gaussian noise at a high error rate, so the
    stream contains decision errors and DFE error propagation (the loop's real use)."""
    rng = get_rng("test_dfe_slicer_noisy")
    cocotb.start_soon(Clock(dut.clk_i, 8, unit="ns").start())
    gen = np.random.default_rng(rng.randrange(1 << 30))
    h0, b, n = 62, 45, 400
    a = gen.choice([-3, -1, 1, 3], n * P)
    zf = h0 * a + b * np.concatenate(([0], a[:-1])) + gen.normal(0, 35, n * P)
    z = np.clip(np.round(zf), ZMIN + 1, ZMAX).astype(int).tolist()
    errs = int(np.count_nonzero(fx.dfe1_int(np.array(z), b, 2 * h0, D_INIT) != (a + 3) // 2))
    assert errs > 20, f"only {errs} decision errors: the test would not exercise propagation"
    await run(dut, rng, b, 2 * h0, z, [rng.random() < 0.8 for _ in range(n)])


@cocotb.test()
async def test_reset_restores_d_init(dut) -> None:  # type: ignore[no-untyped-def]
    """Back-to-back runs: the loop register must restart from D_INIT, whatever the last word
    left in it (run() resets between calls; z chosen so the first decision depends on it)."""
    rng = get_rng("test_dfe_slicer_reset")
    cocotb.start_soon(Clock(dut.clk_i, 8, unit="ns").start())
    b, t2 = 100, 120
    for last in range(4):
        await run(dut, rng, b, t2, [-300 + 200 * last] * (4 * P), [True] * 4)
        await run(dut, rng, b, t2, [10] * P, [True])  # 10 - 100 * level(d0): d0 decides
