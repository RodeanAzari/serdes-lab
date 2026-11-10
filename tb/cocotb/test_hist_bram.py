"""hist_bram vs a Python histogram (clamp to the bin range, saturate at 2^COUNT_W - 1).

The RMW hazards are at clock distance 1 and 2 (rtl header), so the stimulus repeats bins at
distances 1, 2, 3 in clocks, both back to back and through valid gaps (a gap changes the
sample distance but not the clock distance). Each phase is drained and fully read back, and
counts accumulate across phases, so a readout that disturbs the counts also fails. The small
parameter set (IDX_W 4, COUNT_W 4) drives every bin into saturation and both clamp edges.
"""

import os

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge
from tb_common import get_rng

DATA_W = int(os.environ.get("DATA_W", "16"))
IDX_W = int(os.environ.get("IDX_W", "10"))
COUNT_W = int(os.environ.get("COUNT_W", "48"))
NB = 1 << IDX_W
CMAX = (1 << COUNT_W) - 1
DMIN, DMAX = -(1 << (DATA_W - 1)), (1 << (DATA_W - 1)) - 1


class Ref:
    def __init__(self) -> None:
        self.c = [0] * NB

    def add(self, n: int) -> None:
        b = min(max(n, -NB // 2), NB // 2 - 1) + NB // 2
        self.c[b] = min(self.c[b] + 1, CMAX)


async def feed(dut, ref: Ref, seq: list[int | None], rng) -> None:  # type: ignore[no-untyped-def]
    """One entry per clock: a sample, or None for a valid gap (n_i = junk, as upstream logic
    drives while invalid: a junk bin must never reach the counts or the forwarding). Drain."""
    for n in [*seq, None, None, None, None]:
        dut.valid_i.value = int(n is not None)
        junk = rng.randint(-NB // 2, NB // 2 - 1) if rng.random() < 0.5 else rng.randint(-2, 2)
        dut.n_i.value = (n if n is not None else junk) & ((1 << DATA_W) - 1)
        if n is not None:
            ref.add(n)
        await FallingEdge(dut.clk_i)
    dut.valid_i.value = 0


async def read_all(dut) -> list[int]:  # type: ignore[no-untyped-def]
    got: list[int] = []
    for a in [*range(NB), None, None]:
        dut.rd_en_i.value = int(a is not None)
        dut.rd_addr_i.value = a or 0
        await FallingEdge(dut.clk_i)
        if int(dut.rd_valid_o.value):
            got.append(int(dut.rd_data_o.value))
    dut.rd_en_i.value = 0
    assert len(got) == NB, f"{len(got)} readout beats, expected {NB}"
    return got


async def check(dut, ref: Ref, what: str) -> None:  # type: ignore[no-untyped-def]
    got = await read_all(dut)
    bad = [(b, g, e) for b, (g, e) in enumerate(zip(got, ref.c, strict=True)) if g != e]
    assert not bad, f"{what}: {len(bad)} bins differ, first (bin, got, want): {bad[:5]}"


async def clear(dut) -> None:  # type: ignore[no-untyped-def]
    dut.clear_i.value = 1
    await FallingEdge(dut.clk_i)
    dut.clear_i.value = 0
    n = 0
    while int(dut.busy_o.value):
        await FallingEdge(dut.clk_i)
        n += 1
    assert n == NB, f"busy for {n} clocks, expected {NB} (one per bin)"


def hazard_patterns(rng, n: int) -> list[int | None]:  # type: ignore[no-untyped-def]
    """Bins repeated at clock distance 1, 2, 3, with and without gaps, plus runs."""
    out: list[int | None] = []

    def v() -> int:
        return rng.randint(-NB // 2 - 2, NB // 2 + 1)  # includes both clamp edges

    while len(out) < n:
        a, b, c = v(), v(), v()
        out += rng.choice([
            [a] * rng.randint(2, 9),     # distance 1 runs
            [a, b, a, b, a, b],          # distance 2
            [a, b, c, a, b, c],          # distance 3 (no forwarding needed)
            [a, None, a, None, a],       # distance 2 in clocks via gaps
            [a, None, None, a],          # distance 3 in clocks
            [a, b, None, a],             # distance 3, other order
            [a, a, b, a, None, b, b],
        ])  # fmt: skip
    return out


@cocotb.test()
async def test_matches_reference(dut) -> None:  # type: ignore[no-untyped-def]
    rng = get_rng("test_hist_bram")
    dut.rst_i.value = 1
    dut.valid_i.value = 0
    dut.clear_i.value = 0
    dut.rd_en_i.value = 0
    dut.n_i.value = 0
    dut.rd_addr_i.value = 0
    cocotb.start_soon(Clock(dut.clk_i, 8, unit="ns").start())
    await FallingEdge(dut.clk_i)
    await FallingEdge(dut.clk_i)
    dut.rst_i.value = 0
    await clear(dut)
    ref = Ref()
    await check(dut, ref, "after clear")

    span = (-NB // 2 - 4, NB // 2 + 3)  # every bin plus both clamp edges
    rand = [rng.randint(DMIN, DMAX) if rng.random() < 0.1 else rng.randint(*span)
            for _ in range(4000)]  # fmt: skip
    await feed(dut, ref, [n if rng.random() < 0.8 else None for n in rand], rng)
    await check(dut, ref, "random with gaps")

    await feed(dut, ref, hazard_patterns(rng, 6000), rng)
    await check(dut, ref, "hazard patterns")

    narrow = [round(rng.gauss(0, 3)) for _ in range(4000)]  # dense repeats near 0
    await feed(dut, ref, narrow, rng)
    await check(dut, ref, "narrow gaussian")

    gappy = [round(rng.gauss(0, 2)) if rng.random() < 0.6 else None for _ in range(4000)]
    await feed(dut, ref, gappy, rng)  # junk bins in gaps sit next to dense real repeats
    await check(dut, ref, "narrow gaussian with gaps")

    if COUNT_W <= 8:  # drive every bin past saturation, in hazard-heavy order
        sat = [b - NB // 2 for b in range(NB) for _ in range(CMAX + 3)]
        await feed(dut, ref, sat + sat[::-1], rng)
        assert all(c == CMAX for c in ref.c)
        await check(dut, ref, "saturation")

    await clear(dut)
    ref = Ref()
    await check(dut, ref, "second clear")
    await feed(dut, ref, hazard_patterns(rng, 500), rng)
    await check(dut, ref, "after second clear")
