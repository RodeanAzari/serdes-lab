"""demap vs model/pam4.py precode_inverse + gray_to_bits, bit-exact; and the inverse of
pam4_map's mapping (G = {A, A ^ B}). State carries across words, advances only on valid."""

import os

import cocotb
import numpy as np
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge
from tb_common import get_rng

from model import pam4

P = int(os.environ.get("P", "4"))
LATENCY = 1


async def run(dut, rng, precode: bool, d: list[int], valid: list[bool]) -> list[int]:  # type: ignore[no-untyped-def]
    dut.precode_i.value = int(precode)
    dut.rst_i.value = 1
    dut.valid_i.value = 0
    for _ in range(2):
        await FallingEdge(dut.clk_i)
    dut.rst_i.value = 0
    vin: list[int] = []
    g: list[int] = []
    bits: list[int] = []
    pos = 0
    for c in range(len(valid) + LATENCY):
        v = int(dut.valid_o.value)
        want_v = vin[c - LATENCY] if c >= LATENCY else 0
        assert v == want_v, f"clock {c}: valid_o = {v}, expected {want_v}"
        if v:
            gw, bw = dut.g_o.value.to_unsigned(), dut.data_o.value.to_unsigned()
            g += [(gw >> (2 * p)) & 3 for p in range(P)]
            bits += [(bw >> i) & 1 for i in range(2 * P)]
        on = c < len(valid) and valid[c]
        word = d[pos : pos + P] if on else [rng.randrange(4) for _ in range(P)]
        pos += P if on else 0
        dut.d_i.value = sum(s << (2 * p) for p, s in enumerate(word))
        dut.valid_i.value = int(on)
        vin.append(int(on))
        await FallingEdge(dut.clk_i)
    dd = np.asarray(d[:pos], dtype=np.int64)
    want_g = pam4.precode_inverse(dd, 0) if precode else dd
    assert g == want_g.tolist()
    assert bits == pam4.gray_to_bits(want_g).tolist()
    return bits


@cocotb.test()
async def test_random(dut) -> None:  # type: ignore[no-untyped-def]
    rng = get_rng("test_demap")
    cocotb.start_soon(Clock(dut.clk_i, 8, unit="ns").start())
    for trial in range(8):
        n = 150
        valid = [rng.random() < (1.0, 0.5)[trial % 2] for _ in range(n)]
        d = [rng.randrange(4) for _ in range(sum(valid) * P)]
        await run(dut, rng, bool(trial // 2 % 2), d, valid)


@cocotb.test()
async def test_inverts_the_tx_precoder(dut) -> None:  # type: ignore[no-untyped-def]
    """Model TX (Gray map + precoder, P(-1) = 0) then this RX demap returns the TX bits."""
    rng = get_rng("test_demap_tx")
    cocotb.start_soon(Clock(dut.clk_i, 8, unit="ns").start())
    n = 200
    bits = np.array([rng.randrange(2) for _ in range(2 * P * n)], dtype=np.uint8)
    for precode in (False, True):
        g = pam4.bits_to_gray(bits)
        idx = pam4.precode(g, 0) if precode else g
        assert await run(dut, rng, precode, idx.tolist(), [True] * n) == bits.tolist()
