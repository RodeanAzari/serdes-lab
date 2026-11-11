"""ber_core: the docs/registers.md BER protocol end to end (ADR 0012), against the bit-exact
model (model tx -> pre_adc -> front_end -> rx -> count_errors, as test_link_core).

- A run of R bits stops with exactly R bits counted and the model's error counts for them.
- A STATUS while running is a consistent snapshot: its counts equal the model's over the
  first `bits` bits (any prefix, not just R).
- STOP freezes the snapshot; START repeats the identical run from reset.
- Every refusal code, every CONFIG field check at its boundary, truncated datagram dropped.
Handshakes: random tvalid gaps on commands, random tready stalls on replies.
"""

import math
import os

import cocotb
import numpy as np
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge
from tb_common import get_rng
from test_link_core import CFG, TB, channel
from udp_port import Port as UdpPort

from model import prng, rx, tx
from scripts import ber_run

P = int(os.environ.get("P", "4"))
L, N, N_PRE = 16, 16, 4
M0 = P * math.ceil((L + N - 2) / P)
HDR = 39
BUILD_ID = int(os.environ.get("BUILD_ID", "0"))


def be(v: int, n: int) -> bytes:
    return (v & ((1 << (8 * n)) - 1)).to_bytes(n, "big")  # negative: two's complement


def config(r: int, prbs: int, precode: int, sigma: int, lag: int, hold: int, shift: int,
           b: int, t2: int, taps: list[int], coefs: list[int],
           seeds: list[prng.Seed258]) -> bytes:  # fmt: skip
    """docs/registers.md BER CONFIG, built from the table (not from the RTL)."""
    assert len(taps) == L and len(coefs) == N and len(seeds) == P
    return (b"\x01" + be(r, 8) + be(prbs, 4) + be(precode, 1) + be(sigma, 3) + be(lag, 1)
            + be(hold, 2) + be(shift, 1) + be(b, 2) + be(t2, 2)
            + b"".join(be(t, 2) for t in taps) + b"".join(be(c, 2) for c in coefs)
            + b"".join(be(w, 8) for s in seeds for w in s))  # fmt: skip


class Port(UdpPort):
    async def cmd(self, data: bytes) -> dict[str, int]:
        await self.send(data)
        r = await self.recv()
        assert len(r) == HDR, f"reply length {len(r)}"
        f = r[2]
        assert f >> 4 == 0, f"reserved flag bits {f:#x}"
        st = {
            "op": r[0], "code": r[1], "running": f & 1, "configured": (f >> 1) & 1,
            "reached": (f >> 2) & 1, "fifo_err": (f >> 3) & 1,
            "bits": int.from_bytes(r[3:11], "big"), "bit_err": int.from_bytes(r[11:19], "big"),
            "sym_err": int.from_bytes(r[19:27], "big"), "runlen": int.from_bytes(r[27:35], "big"),
            "build": int.from_bytes(r[35:39], "big"),
        }  # fmt: skip
        assert st["build"] == BUILD_ID
        return st


async def start(dut, name: str) -> Port:  # type: ignore[no-untyped-def]
    for s in ("s_tvalid_i", "s_tlast_i", "s_tuser_i", "m_tready_i", "s_tdata_i"):
        getattr(dut, s).value = 0
    dut.rst_i.value = 1
    cocotb.start_soon(Clock(dut.clk_i, 8, unit="ns").start())
    for _ in range(3):
        await FallingEdge(dut.clk_i)
    dut.rst_i.value = 0
    return Port(dut, get_rng(name))


class Case:
    """One link configuration and the model's RX/TX Gray streams for it."""

    def __init__(self, rng, name: str, precoder: bool, sigma: int, hold: int,  # type: ignore[no-untyped-def]
                 n_cw: int) -> None:  # fmt: skip
        hq, cursor, regs = channel(name)
        self.k, self.hold = cursor + N_PRE, hold
        prbs_seed = rng.getrandbits(31) or 1
        seeds = prng.lane_seeds(rng.getrandbits(64), P)
        t = tx.tx(n_cw, prbs_seed, precoder)
        y = tx.pre_adc(t.a, np.array(hq, dtype=np.int64), cursor, seeds, TB, sigma)
        x_hw = tx.front_end(y, CFG)[tx.valid(len(t.a), L, cursor)]
        out = rx.rx(x_hw, regs, CFG, precoder, d_init=0, p_init=0, start=M0 - (L - 1))
        self.rx_gray, self.tx_gray = out.gray, t.gray
        # RX words the model covers, less the holdoff: the longest R the model can check
        self.max_words = min(len(out.gray) // P, (len(t.gray) - (M0 - self.k)) // P) - hold
        self.args = dict(prbs=prbs_seed, precode=int(precoder), sigma=sigma, lag=self.k,
                         hold=hold, shift=regs.out_shift, b=int(regs.dfe_b), t2=int(regs.t2),
                         taps=hq + [0] * (L - len(hq)), coefs=[int(c) for c in regs.coefs],
                         seeds=seeds)  # fmt: skip

    def cfg(self, r: int) -> bytes:
        return config(r, **self.args)  # type: ignore[arg-type]

    def model(self, bits: int) -> rx.ErrCount:
        """Model counts over the first `bits` counted bits (after the holdoff)."""
        assert bits % (2 * P) == 0 and bits // (2 * P) <= self.max_words, bits
        n_sym = self.hold * P + bits // 2
        return rx.count_errors(self.rx_gray[:n_sym], self.tx_gray, M0 - self.k, self.hold * P)


def counts(st: dict[str, int]) -> rx.ErrCount:
    return rx.ErrCount(st["bits"], st["bit_err"], st["sym_err"])


async def until(port: Port, key: str, val: int, tries: int = 2000) -> dict[str, int]:
    for _ in range(tries):
        st = await port.cmd(b"\x05")
        if st[key] == val:
            return st
    raise AssertionError(f"STATUS {key} never became {val}")


@cocotb.test()
async def test_runs_match_model(dut) -> None:  # type: ignore[no-untyped-def]
    """sigma ~3x the 1e-12 operating point: hundreds of errors with DFE propagation."""
    port = await start(dut, "test_ber_core_runs")
    for name, sigma, pre, hold in (("kr_ch4_31p4db", 4800, False, 0),
                                   ("kr_ch2_19p3db", 7000, True, 3)):  # fmt: skip
        c = Case(port.rng, name, pre, sigma, hold, 3)
        r = 2 * P * (c.max_words - port.rng.randrange(4))
        st = await port.cmd(c.cfg(r))
        assert st["code"] == 0 and st["configured"] and not st["running"], st
        assert st["runlen"] == r and counts(st) == rx.ErrCount(0, 0, 0)

        # 1. run to R: exact length, model counts; mid-run snapshots are consistent prefixes
        st = await port.cmd(b"\x02")
        assert st["code"] == 0 and st["running"] and not st["reached"]
        mids = 0
        while not (st := await port.cmd(b"\x05"))["reached"]:
            assert st["running"] and st["bits"] < r
            assert counts(st) == c.model(st["bits"]), f"mid-run snapshot at {st['bits']} bits"
            mids += st["bits"] > 0
        assert mids >= 3, "too few mid-run snapshots to test consistency"
        want = c.model(r)
        assert not st["running"] and not st["fifo_err"] and counts(st) == want, (st, want)
        assert want.sym_errors > 100, f"only {want.sym_errors} symbol errors"
        dut._log.info(f"{name} pre {pre}: R {r} -> {want}, {mids} mid-run snapshots")
        assert counts(await port.cmd(b"\x05")) == want  # frozen after the stop

        # 2. START repeats the identical run from reset
        assert (await port.cmd(b"\x02"))["code"] == 0
        st = await until(port, "reached", 1)
        assert counts(st) == want

        # 3. STOP mid-run freezes a consistent snapshot; CONFIG/START refused while running
        assert (await port.cmd(b"\x02"))["code"] == 0
        assert (await port.cmd(b"\x02"))["code"] == 1
        assert (await port.cmd(c.cfg(r)))["code"] == 1
        st = await port.cmd(b"\x03")
        assert st["code"] == 0 and not st["running"] and not st["reached"] and 0 < st["bits"] < r
        assert counts(st) == c.model(st["bits"])
        st2 = await port.cmd(b"\x05")
        assert counts(st2) == counts(st) and not st2["running"]

    # 4. R = 0: unbounded, runs past the model's span until STOP
    st = await port.cmd(c.cfg(0))
    assert st["code"] == 0 and st["runlen"] == 0
    await port.cmd(b"\x02")
    while (st := await port.cmd(b"\x05"))["bits"] <= 2 * P * (c.max_words + 50):
        assert st["running"]
    assert not (await port.cmd(b"\x03"))["running"]


@cocotb.test()
async def test_protocol_errors(dut) -> None:  # type: ignore[no-untyped-def]
    port = await start(dut, "test_ber_core_protocol")
    st = await port.cmd(b"\x05")
    assert st["code"] == 0 and st["op"] == 0x85 and not st["configured"] and st["bits"] == 0
    st = await port.cmd(b"\x42")
    assert st["op"] == 0xFF and st["code"] == 4
    assert (await port.cmd(b"\x04\x00\x00"))["code"] == 4  # the noise board's READ: not here

    seeds = prng.lane_seeds(7, P)
    # every field at its limit
    good = dict(r=2 * P * 10, prbs=1, precode=1, sigma=(1 << 17) - 1, lag=M0, hold=0xFFFF,
                shift=15, b=-512, t2=1023, taps=[-1024] + [1023] * (L - 1),
                coefs=[511] * (N - 1) + [-512], seeds=seeds)  # fmt: skip
    cfg = config(**good)  # type: ignore[arg-type]
    assert len(cfg) == 25 + 2 * L + 2 * N + 40 * P
    for bad in (b"\x05\x00", b"\x02\x00", b"\x03\x00", cfg[:-1], cfg + b"\x00"):
        st = await port.cmd(bad)
        assert st["code"] == 2 and st["op"] == bad[0] | 0x80, f"length {len(bad)} op {bad[0]}"
    assert (await port.cmd(b"\x02"))["code"] == 1  # START before CONFIG

    bad_seed = [list(s) for s in seeds]
    bad_seed[P - 1][4] = (1 << 23) - 1  # y5 needs a bit at or above 2^23
    for k, v in (("r", 2 * P * 10 + P), ("prbs", 0), ("prbs", 1 << 31), ("prbs", (1 << 31) | 1),
                 ("precode", 2),
                 ("sigma", 1 << 17), ("lag", M0 + 1), ("shift", 16), ("b", 512), ("b", -513),
                 ("t2", 1024), ("taps", [0] * (L - 1) + [1024]), ("taps", [-1025] + [0] * (L - 1)),
                 ("coefs", [0] * (N - 1) + [512]), ("coefs", [-513] + [0] * (N - 1)),
                 ("seeds", [tuple(s) for s in bad_seed])):  # fmt: skip
        st = await port.cmd(config(**{**good, k: v}))  # type: ignore[arg-type]
        assert st["code"] == 3 and not st["configured"], f"{k} = {v} accepted"

    st = await port.cmd(cfg)  # every field at its limit: accepted
    assert st["code"] == 0 and st["configured"] and st["runlen"] == 2 * P * 10
    assert (await port.cmd(config(**{**good, "r": 2 * P * 11 + 2 * P})))["code"] == 0
    # truncated datagram: no reply, next command answered normally
    await port.send(b"\x05", truncated=True)
    assert (await port.cmd(b"\x05"))["op"] == 0x85
    # STOP when idle: accepted, nothing changes
    st = await port.cmd(b"\x03")
    assert st["code"] == 0 and not st["running"] and st["configured"]


@cocotb.test(skip=P != ber_run.P)
async def test_host_script_config(dut) -> None:  # type: ignore[no-untyped-def]
    """scripts/ber_run.py packs CONFIG and computes the model reference for `exact` on its own;
    check both against the RTL here, before the board: same counts over the same R."""
    port = await start(dut, "test_ber_core_host")
    for ch, snr, pre in (("kr_ch4_31p4db", 19.0, False), ("kr_ch2_19p3db", 15.0, True)):
        pt = ber_run.point(ch, snr, pre, port.rng.getrandbits(32))
        want, r = ber_run.model_counts(pt, 3)
        assert (await port.cmd(pt.config(r)))["code"] == 0
        assert (await port.cmd(b"\x02"))["code"] == 0
        st = await until(port, "reached", 1)
        assert counts(st) == want and want.bit_errors > 50, (ch, snr, counts(st), want)
        dut._log.info(f"host config {ch} {snr} dB pre {pre}: {want}")
