"""gearbox: output bit stream == input symbols MSB first, under random input starvation."""

import os

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge
from tb_common import get_rng

IN_W = int(os.environ.get("IN_W", "10"))
OUT_W = int(os.environ.get("OUT_W", "8"))


async def run(dut, rng, n_sym: int, p_valid: float) -> None:  # type: ignore[no-untyped-def]
    dut.rst_i.value = 1
    dut.s_valid_i.value = 0
    await FallingEdge(dut.clk_i)
    await FallingEdge(dut.clk_i)
    dut.rst_i.value = 0
    syms = [rng.getrandbits(IN_W) for _ in range(n_sym)]
    want = [(s >> (IN_W - 1 - j)) & 1 for s in syms for j in range(IN_W)]
    got: list[int] = []
    i, started, cyc = 0, False, 0
    # slower side: input n_sym/p_valid clocks (sigma ~56 at 0.3), output len(want)/OUT_W
    max_cyc = int(1.5 * max(n_sym / p_valid, len(want) / OUT_W)) + 100
    while len(got) + OUT_W <= len(want):
        cyc += 1
        assert cyc < max_cyc, f"stalled: {len(got)}/{len(want)} bits after {cyc} clocks (deadlock?)"
        # sample outputs for the edge to come (inputs settled at this falling edge)
        v = int(dut.valid_o.value)
        if p_valid == 1.0 and IN_W >= OUT_W and i < n_sym:  # fed every clock: never underrun
            assert v or not started, f"valid_o dropped with input available ({len(got)} bits out)"
        started = started or bool(v)
        if v:
            d = int(dut.data_o.value)
            got += [(d >> b) & 1 for b in range(OUT_W)]
        offer = i < n_sym and rng.random() < p_valid
        dut.s_valid_i.value = int(offer)
        dut.s_data_i.value = syms[i] if offer else rng.getrandbits(IN_W)  # junk when invalid
        await cocotb.triggers.Timer(1, unit="ns")  # let s_ready_o settle on the new inputs
        if offer and int(dut.s_ready_o.value):
            i += 1
        await FallingEdge(dut.clk_i)
    assert got == want[: len(got)], "bit stream differs"
    assert len(got) >= len(want) - OUT_W + 1


@cocotb.test()
async def test_stream(dut) -> None:  # type: ignore[no-untyped-def]
    rng = get_rng("test_gearbox")
    cocotb.start_soon(Clock(dut.clk_i, 8, unit="ns").start())
    for p in (0.3, 0.8, 1.0):
        await run(dut, rng, 400, p)
