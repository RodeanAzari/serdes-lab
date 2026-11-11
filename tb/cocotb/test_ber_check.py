"""ber_check vs model/rx.py count_errors (ADR 0011), exact counts.

TX and RX words are driven independently with random valid gaps, the FIFO kept anywhere from
empty to full; first_i covers every offset mod P and holdoff_i spans 0 to past the end. Counters
saturate at CNT_W bits; err_o flags FIFO overflow and underflow only.
"""

import os

import cocotb
import numpy as np
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge
from tb_common import get_rng

from model import pam4, rx

P = int(os.environ.get("P", "4"))
DEPTH = int(os.environ.get("DEPTH", "64"))
CNT_W = int(os.environ.get("CNT_W", "64"))
CMAX = (1 << CNT_W) - 1
DRAIN = 3  # counters follow an accepted RX word after 2 clocks


def pack(g: list[int]) -> int:
    """Gray symbols -> stream-order bits: symbol s at [2s] = A, [2s + 1] = B (demap)."""
    b = pam4.gray_to_bits(np.asarray(g, dtype=np.int64))
    return sum(int(v) << i for i, v in enumerate(b))


def c0_of(first: int) -> int:
    """First TX word that writes the FIFO (ber_check header)."""
    return first // P + (first % P != 0)


async def reset(dut, first: int, holdoff: int) -> None:  # type: ignore[no-untyped-def]
    dut.first_i.value = first
    dut.holdoff_i.value = holdoff
    dut.tx_valid_i.value = 0
    dut.rx_valid_i.value = 0
    dut.rst_i.value = 1
    for _ in range(2):
        await FallingEdge(dut.clk_i)
    dut.rst_i.value = 0


async def run(dut, rng, first: int, holdoff: int, n_rx: int, p_err: float,  # type: ignore[no-untyped-def]
              p_tx: float, p_rx: float) -> rx.ErrCount:  # fmt: skip
    """n_rx RX words against a random TX stream; returns the model's count after checking it."""
    await reset(dut, first, holdoff)
    c0 = c0_of(first)
    n_tx = c0 + n_rx
    tx_g = [rng.randrange(4) for _ in range((n_tx + 1) * P)]
    rx_g = list(tx_g[first : first + n_rx * P])
    for j in range(len(rx_g)):
        if rng.random() < p_err:
            rx_g[j] = (rx_g[j] + rng.randrange(1, 4)) % 4
    sent_tx = sent_rx = 0
    level = 0  # FIFO words, as the RTL sees them at the clock edge
    while sent_rx < n_rx:
        do_tx = sent_tx < n_tx and rng.random() < p_tx and level < DEPTH
        do_rx = level > 0 and rng.random() < p_rx  # never underflow here
        dut.tx_valid_i.value = int(do_tx)
        dut.tx_bits_i.value = pack(tx_g[sent_tx * P : (sent_tx + 1) * P]) if do_tx else 0
        dut.rx_valid_i.value = int(do_rx)
        dut.rx_bits_i.value = pack(rx_g[sent_rx * P : (sent_rx + 1) * P]) if do_rx else 0
        level += int(do_tx and sent_tx >= c0) - int(do_rx)
        sent_tx += int(do_tx)
        sent_rx += int(do_rx)
        await FallingEdge(dut.clk_i)
    dut.tx_valid_i.value = 0
    dut.rx_valid_i.value = 0
    for _ in range(DRAIN):
        await FallingEdge(dut.clk_i)
    want = rx.count_errors(np.array(rx_g), np.array(tx_g), first, holdoff * P)
    got = rx.ErrCount(int(dut.bits_o.value), int(dut.bit_err_o.value), int(dut.sym_err_o.value))
    sat = rx.ErrCount(min(want.bits, CMAX), min(want.bit_errors, CMAX), min(want.sym_errors, CMAX))
    assert got == sat, f"first {first} holdoff {holdoff}: got {got}, want {sat}"
    assert int(dut.err_o.value) == 0, "err_o set on a legal stream"
    return want


@cocotb.test()
async def test_random(dut) -> None:  # type: ignore[no-untyped-def]
    rng = get_rng("test_ber_check")
    cocotb.start_soon(Clock(dut.clk_i, 8, unit="ns").start())
    for trial in range(24):
        first = trial % (2 * P + 3) if trial < 12 else rng.randrange(0, 100)
        holdoff = rng.choice([0, 1, rng.randrange(0, 30), 1000])  # 1000 > n_rx: counts 0
        p_tx, p_rx = rng.choice([(1.0, 1.0), (0.9, 0.5), (0.5, 0.9), (0.3, 0.3)])
        await run(dut, rng, first, holdoff, 60, rng.choice([0.0, 0.05, 0.5, 1.0]), p_tx, p_rx)


@cocotb.test()
async def test_every_symbol_wrong_by_every_amount(dut) -> None:  # type: ignore[no-untyped-def]
    """p_err 1: each symbol replaced by one of the 3 others (1 or 2 bit errors per symbol)."""
    rng = get_rng("test_ber_check_all")
    cocotb.start_soon(Clock(dut.clk_i, 8, unit="ns").start())
    w = await run(dut, rng, 5, 0, 200, 1.0, 1.0, 1.0)
    assert w.sym_errors == w.bits // 2 and w.bits // 2 < w.bit_errors < w.bits


@cocotb.test()
async def test_underflow_sets_err(dut) -> None:  # type: ignore[no-untyped-def]
    cocotb.start_soon(Clock(dut.clk_i, 8, unit="ns").start())
    await reset(dut, 3, 0)
    dut.rx_valid_i.value = 1
    await FallingEdge(dut.clk_i)
    dut.rx_valid_i.value = 0
    await FallingEdge(dut.clk_i)
    assert int(dut.err_o.value) == 1
    assert int(dut.bits_o.value) == 0, "an RX word with no reference must not be counted"
    await reset(dut, 3, 0)
    assert int(dut.err_o.value) == 0, "reset clears err_o"


@cocotb.test()
async def test_overflow_sets_err(dut) -> None:  # type: ignore[no-untyped-def]
    """c0 + DEPTH TX words fill the FIFO exactly (no flag); one more overflows."""
    cocotb.start_soon(Clock(dut.clk_i, 8, unit="ns").start())
    first = 2 * P + 1
    for extra in (0, 1):
        await reset(dut, first, 0)
        dut.tx_valid_i.value = 1
        for _ in range(c0_of(first) + DEPTH + extra):
            await FallingEdge(dut.clk_i)
        dut.tx_valid_i.value = 0
        await FallingEdge(dut.clk_i)
        assert int(dut.err_o.value) == extra, f"{extra} words past full"
