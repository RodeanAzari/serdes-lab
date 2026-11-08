"""lfsr258 vs model/prng.py (itself bit-exact vs the reference C): random enables, reseed."""

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge
from tb_common import InOrderScoreboard, get_rng

from model import prng


async def run_seed(dut, rng, seed: prng.Seed258, n_words: int, p_en: float) -> None:  # type: ignore[no-untyped-def]
    await FallingEdge(dut.clk_i)
    dut.rst_i.value = 1
    dut.seed_i.value = sum(w << (64 * i) for i, w in enumerate(seed))
    dut.en_i.value = 0
    await FallingEdge(dut.clk_i)
    dut.rst_i.value = 0
    dut.seed_i.value = 0  # ignored outside reset
    assert int(dut.valid_o.value) == 0, "valid_o must be low after reset"
    sb = InOrderScoreboard(f"lfsr258 seed={seed[0]:#x}", fmt=lambda v: f"{v:#018x}")
    for w in prng.lfsr258_words(n_words, [seed])[:, 0]:
        sb.expect(int(w))
    got, prev_en, held = 0, False, None
    while got < n_words:
        if prev_en:  # a step happened at the rising edge just passed
            assert int(dut.valid_o.value) == 1
            held = int(dut.word_o.value)
            sb.observe(held)
            got += 1
        elif held is not None:
            assert int(dut.word_o.value) == held, "word_o changed without en_i"
        else:
            assert int(dut.valid_o.value) == 0, "valid_o before the first enabled clock"
        prev_en = rng.random() < p_en
        dut.en_i.value = int(prev_en)
        await FallingEdge(dut.clk_i)
    sb.check_done()


@cocotb.test()
async def test_matches_model(dut) -> None:  # type: ignore[no-untyped-def]
    rng = get_rng("test_lfsr258")
    dut.rst_i.value = 1  # held from time 0, as the board reset sync does
    dut.en_i.value = 0
    cocotb.start_soon(Clock(dut.clk_i, 8, unit="ns").start())
    seeds = [prng.check_seed258(prng.SEED_MIN), *prng.lane_seeds(rng.getrandbits(64), 3)]
    for s in seeds:
        await run_seed(dut, rng, s, 300, p_en=0.6)
    await run_seed(dut, rng, prng.lane_seeds(rng.getrandbits(64), 1)[0], 300, p_en=1.0)
