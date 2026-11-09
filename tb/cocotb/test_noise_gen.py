"""noise_gen vs model/noise.py noise(), bit-exact, every lane (ADR 0003 validation step 2).

Expected values come from the model's tables (build_tables), not from the ROM file, so a stale
or mis-packed rtl/channel/noise_tables.mem fails here too.

Stimulus per sigma: every reachable (octave, sub-segment) on every lane, each with a random, an
all-zero and an all-one x field (x = 0 and x = 2^17 - 1), random signs, plus u = 0; then random
words with valid gaps. Sigma values: an operating point (Ch4 1e-12), 0, 1, 2^16 (makes rounding
ties common: g*sigma = 2^24 mod 2^25 whenever g = 256 mod 512, so sign-before-rounding shows),
and the maximum (saturates). valid_o must be valid_i delayed by 13; a reset drops in-flight words.
"""

import os
from collections import deque

import cocotb
import numpy as np
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge
from tb_common import get_rng

from model import noise as nz

P = int(os.environ.get("P", "4"))
LATENCY = 13
CFG = nz.NoiseCfg()
TB = nz.build_tables(CFG)  # ~20 s
SIGMAS = [round(49.4 * 32), 0, 1, 1 << 16, (1 << 17) - 1]
NMAX = (1 << 15) - 1


def to_signed(v: int, w: int) -> int:
    return v - (1 << w) if v >> (w - 1) else v


def segment_words(rng) -> list[int]:  # type: ignore[no-untyped-def]
    """u for every reachable segment x {random, zero, all-one} tail, random sign; plus u = 0."""
    us = [0]
    for o in range(63):
        b = 62 - o  # bits after the leading one
        for sub in range(16):
            if b >= 4:
                tb = b - 4
                for tail in (rng.getrandbits(tb) if tb else 0, 0, (1 << tb) - 1):
                    us.append((1 << b) | (sub << tb) | tail)
            elif sub % (1 << (4 - b)) == 0:  # only these subs exist with b < 4 bits
                us.append((1 << b) | (sub >> (4 - b)))
    return [u | (rng.getrandbits(1) << 63) for u in us]


def tie_words(rng, sigma: int, n: int) -> list[int]:  # type: ignore[no-untyped-def]
    """n words whose g*sigma is a rounding tie (= 2^24 mod 2^25), found with the model."""
    out: list[int] = []
    while len(out) < n:
        w = np.array([rng.getrandbits(64) for _ in range(50000)], dtype=np.uint64)
        g = nz.gauss_mag(w & np.uint64((1 << 63) - 1), TB)
        out += [int(x) for x in w[(g * sigma) % (1 << 25) == (1 << 24)]]
    return out[:n]


async def drive(dut, sigma: int, cycles: list[tuple[bool, list[int]]]) -> dict[str, int]:  # type: ignore[no-untyped-def]
    """Drive (valid, P words) per clock with sigma fixed, drain, check every output."""
    dut.sigma_i.value = sigma
    vw = [w for v, ws in cycles if v for w in ws]
    exp_all = nz.noise(np.array(vw, dtype=np.uint64), TB, sigma).tolist() if vw else []
    pending: deque[tuple[int, list[int]]] = deque()
    stats = {"words": len(vw), "sat": sum(abs(e) == NMAX for e in exp_all), "ties": 0}
    if vw and sigma:
        g = nz.gauss_mag(np.array(vw, dtype=np.uint64) & np.uint64((1 << 63) - 1), TB)
        stats["ties"] = int(np.sum((g * sigma) % (1 << 25) == (1 << 24)))
    pos = 0
    for c, (v, ws) in enumerate([*cycles, *[(False, [0] * P)] * (LATENCY + 1)]):
        check_output(dut, c, pending)
        dut.valid_i.value = int(v)
        dut.word_i.value = sum(w << (64 * k) for k, w in enumerate(ws))
        if v:
            pending.append((c + LATENCY, exp_all[pos : pos + P]))
            pos += P
        await FallingEdge(dut.clk_i)
    assert not pending, f"{len(pending)} words never came out"
    return stats


def check_output(dut, c: int, pending: deque[tuple[int, list[int]]]) -> None:  # type: ignore[no-untyped-def]
    if int(dut.valid_o.value):
        assert pending, f"cycle {c}: valid_o with nothing in flight"
        due, exp = pending.popleft()
        assert due == c, f"valid_o at cycle {c}, expected latency {LATENCY} (due {due})"
        raw = int(dut.n_o.value)
        got = [to_signed((raw >> (16 * k)) & 0xFFFF, 16) for k in range(P)]
        assert got == exp, f"cycle {c}: n_o {got} != model {exp}"
    else:
        assert not pending or pending[0][0] != c, f"cycle {c}: valid_o low, a word was due"


async def reset(dut) -> None:  # type: ignore[no-untyped-def]
    dut.rst_i.value = 1
    dut.valid_i.value = 0
    await FallingEdge(dut.clk_i)
    dut.rst_i.value = 0


@cocotb.test()
async def test_matches_model(dut) -> None:  # type: ignore[no-untyped-def]
    rng = get_rng("test_noise_gen")
    dut.rst_i.value = 1  # held from time 0, as the board reset sync does
    dut.valid_i.value = 0
    dut.word_i.value = 0
    dut.sigma_i.value = 0
    cocotb.start_soon(Clock(dut.clk_i, 8, unit="ns").start())
    await FallingEdge(dut.clk_i)
    await FallingEdge(dut.clk_i)
    await reset(dut)
    seg = segment_words(rng)
    for sigma in SIGMAS:
        lanes = [rng.sample(seg, len(seg)) for _ in range(P)]  # each lane sees every segment
        cycles = [(True, [lanes[k][i] for k in range(P)]) for i in range(len(seg))]
        if sigma == 1 << 16:
            ties = tie_words(rng, sigma, 200 * P)
            cycles += [(True, ties[i : i + P]) for i in range(0, len(ties), P)]
        cycles += [(rng.random() < 0.7, [rng.getrandbits(64) for _ in range(P)])
                   for _ in range(2000)]  # fmt: skip
        st = await drive(dut, sigma, cycles)
        dut._log.info(f"sigma_reg={sigma}: {st}")
        if sigma == 1 << 16:
            assert st["ties"] > 100, "sigma 2^16 must exercise rounding ties"
        if sigma == SIGMAS[-1]:
            assert st["sat"] > 100, "max sigma must exercise saturation"


@cocotb.test()
async def test_reset_drops_in_flight_words(dut) -> None:  # type: ignore[no-untyped-def]
    rng = get_rng("test_noise_gen_reset")
    dut.word_i.value = 0
    dut.sigma_i.value = SIGMAS[0]
    cocotb.start_soon(Clock(dut.clk_i, 8, unit="ns").start())
    await reset(dut)
    for _ in range(LATENCY + 2):  # nothing driven: valid_o must stay low
        assert int(dut.valid_o.value) == 0, "valid_o without input"
        await FallingEdge(dut.clk_i)
    dut.valid_i.value = 1
    for _ in range(LATENCY // 2):
        dut.word_i.value = rng.getrandbits(64 * P)
        await FallingEdge(dut.clk_i)
    await reset(dut)  # words in flight are dropped
    for _ in range(LATENCY + 2):
        assert int(dut.valid_o.value) == 0, "valid_o after reset for a word sent before it"
        await FallingEdge(dut.clk_i)
    # and the pipeline still works afterwards
    await drive(dut, SIGMAS[0], [(True, [rng.getrandbits(64) for _ in range(P)])
                                      for _ in range(50)])  # fmt: skip

