"""tx_top vs model/tx.py tx(): PRBS -> RS encode -> gearbox -> Gray/precoder, bit-exact."""

import os

import cocotb
import numpy as np
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge
from tb_common import get_rng

from model import rs, tx

P = int(os.environ.get("P", "4"))
N_CW = 3
LATENCY = 2  # reset release -> first valid word (tx_top header)


def signed3(v: int) -> int:
    return v - 8 if v & 4 else v


async def run(dut, seed: int, precoder: bool) -> None:  # type: ignore[no-untyped-def]
    dut.rst_i.value = 1
    dut.prbs_seed_i.value = seed
    dut.precode_i.value = int(precoder)
    for _ in range(3):
        await FallingEdge(dut.clk_i)
    dut.rst_i.value = 0
    ref = tx.tx(N_CW, seed, precoder)
    n_words = len(ref.a) // P
    a, idx, cyc, started = [], [], 0, False
    while len(a) < n_words * P:
        await FallingEdge(dut.clk_i)
        cyc += 1
        v = int(dut.valid_o.value)
        if not started:
            if v:
                assert cyc == LATENCY, f"first valid word after {cyc} clocks, expected {LATENCY}"
                started = True
            else:
                continue
        assert v, f"valid_o dropped at clock {cyc}"  # the channel needs a word every clock
        aw, iw = dut.a_o.value.to_unsigned(), dut.idx_o.value.to_unsigned()
        for s in range(P):
            a.append(signed3((aw >> (3 * s)) & 7))
            idx.append((iw >> (2 * s)) & 3)
    a_ref, i_ref = ref.a.tolist(), ref.idx.tolist()
    for k in range(len(a)):  # first mismatch, with its place in the codeword
        if a[k] != a_ref[k] or idx[k] != i_ref[k]:
            cw, pos = divmod(k, rs.N * rs.M // 2)
            where = f"symbol {k} (codeword {cw}, PAM4 {pos}, RS symbol {pos // 5})"
            got, want = f"a={a[k]} idx={idx[k]}", f"a={a_ref[k]} idx={i_ref[k]}"
            raise AssertionError(f"{where}: got {got}, want {want}")
    assert len(a) == len(a_ref)


@cocotb.test()
async def test_matches_model(dut) -> None:  # type: ignore[no-untyped-def]
    rng = get_rng("test_tx_top")
    dut.rst_i.value = 1
    cocotb.start_soon(Clock(dut.clk_i, 8, unit="ns").start())
    for precoder in (False, True):
        await run(dut, rng.randrange(1, 1 << 31), precoder)
    await run(dut, 1, True)  # seed 1: long zero runs at the start


@cocotb.test()
async def test_seeds_differ(dut) -> None:  # type: ignore[no-untyped-def]
    """Guard against a test that passes because the output ignores the seed."""
    a = tx.tx(1, 5, False).a
    b = tx.tx(1, 6, False).a
    assert not np.array_equal(a, b)
    dut.rst_i.value = 1
    cocotb.start_soon(Clock(dut.clk_i, 8, unit="ns").start())
    await run(dut, 6, False)
