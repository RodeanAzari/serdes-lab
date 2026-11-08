"""prbs31_par vs model/prng.py prbs31: random enable gaps, reseed mid-run, W from the runner."""

import os

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge
from tb_common import InOrderScoreboard, get_rng

from model import prng

W = int(os.environ.get("W", "10"))


async def run_seed(dut, rng, seed: int, n_words: int, p_en: float) -> None:  # type: ignore[no-untyped-def]
    """Reset with seed, collect n_words enabled outputs, compare bit-exact to the model."""
    await FallingEdge(dut.clk_i)
    dut.rst_i.value = 1
    dut.seed_i.value = seed
    dut.en_i.value = 0
    await FallingEdge(dut.clk_i)
    dut.rst_i.value = 0
    dut.seed_i.value = rng.getrandbits(31)  # ignored outside reset
    sb = InOrderScoreboard(f"prbs31 W={W} seed={seed:#x}", fmt=lambda v: f"{v:#x}")
    ref = prng.prbs31(n_words * W, seed).reshape(n_words, W)
    for row in ref:
        sb.expect(sum(int(b) << i for i, b in enumerate(row)))
    got = 0
    while got < n_words:
        en = rng.random() < p_en
        dut.en_i.value = int(en)
        if en:  # this window is consumed by the next rising edge
            sb.observe(int(dut.data_o.value))
            got += 1
        await FallingEdge(dut.clk_i)
    sb.check_done()


@cocotb.test()
async def test_matches_model(dut) -> None:  # type: ignore[no-untyped-def]
    rng = get_rng("test_prbs31_par")
    dut.rst_i.value = 1  # held from time 0, as the board reset sync does
    dut.en_i.value = 0
    cocotb.start_soon(Clock(dut.clk_i, 8, unit="ns").start())
    n = max(64, 2000 // W)  # >= 2000 bits: many wraps of the 31-bit window
    for seed in (1, 0x7FFFFFFF, rng.randrange(1, 1 << 31)):
        await run_seed(dut, rng, seed, n, p_en=0.6)
    await run_seed(dut, rng, rng.randrange(1, 1 << 31), n, p_en=1.0)  # back-to-back enables
