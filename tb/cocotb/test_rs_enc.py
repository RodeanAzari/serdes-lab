"""rs_enc vs model/rs.py encode (itself verified vs galois): random gaps and backpressure."""

import cocotb
import numpy as np
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, FallingEdge
from tb_common import InOrderScoreboard, get_rng
from tb_common.axis import AxisSink, AxisSource

from model import rs


async def run(dut, msgs: np.ndarray, p_valid: float, p_ready: float, name: str) -> None:  # type: ignore[no-untyped-def]
    rng = get_rng(name)
    dut.rst_i.value = 1
    dut.s_axis_tvalid_i.value = 0
    dut.m_axis_tready_i.value = 0
    await ClockCycles(dut.clk_i, 2)
    await FallingEdge(dut.clk_i)
    dut.rst_i.value = 0
    sb = InOrderScoreboard(name, fmt=lambda f: f"codeword ({len(f)} symbols) {list(f[:4])}...")
    for cw in rs.encode(msgs):
        sb.expect(tuple(int(v) for v in cw))

    def got(frame) -> None:  # type: ignore[no-untyped-def]
        sb.observe(tuple(b.data for b in frame))

    sink = AxisSink(dut, dut.clk_i, "m_axis_", rng=rng, p_ready=p_ready, callback=got)
    src = AxisSource(dut, dut.clk_i, "s_axis_", rng=rng, p_valid=p_valid)
    await src.send_frame([int(v) for v in msgs.reshape(-1)])
    await sink.wait_frames(len(msgs))
    sb.check_done()
    for f in sink.frames:  # tlast exactly on symbol N-1 of every codeword
        assert len(f) == rs.N and [b.last for b in f].count(True) == 1


@cocotb.test()
async def test_random(dut) -> None:  # type: ignore[no-untyped-def]
    cocotb.start_soon(Clock(dut.clk_i, 8, unit="ns").start())
    r = np.random.default_rng(get_rng("test_rs_enc msgs").getrandbits(32))
    msgs = r.integers(0, 1 << rs.M, size=(4, rs.K))
    msgs[1] = 0  # all-zero codeword: parity must be 0
    msgs[2] = (1 << rs.M) - 1  # every bit set
    await run(dut, msgs, p_valid=0.7, p_ready=0.6, name="test_rs_enc gaps")


@cocotb.test()
async def test_full_rate(dut) -> None:  # type: ignore[no-untyped-def]
    cocotb.start_soon(Clock(dut.clk_i, 8, unit="ns").start())
    r = np.random.default_rng(get_rng("test_rs_enc full").getrandbits(32))
    await run(dut, r.integers(0, 1 << rs.M, size=(3, rs.K)), 1.0, 1.0, "test_rs_enc full")
