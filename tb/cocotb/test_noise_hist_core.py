"""noise_hist_core: the docs/registers.md protocol end to end, and the ADR 0009 exactness check
in simulation: after CONFIG(seeds, sigma, N) + START, every lane's histogram read back over the
protocol equals np.bincount of the model's noise for exactly N words (bin for bin).

Also: every error code, a pause/resume run giving the same histogram as an unbroken one, READ
refused while running, a truncated datagram dropped without reply, clamping at max sigma.
Handshakes: random tvalid gaps on commands, random tready stalls on replies.
"""

import os

import cocotb
import numpy as np
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge
from tb_common import get_rng
from udp_port import Port as UdpPort

from model import noise, prng

TB = noise.build_tables(noise.NoiseCfg())  # ~20 s
BUILD_ID = int(os.environ.get("BUILD_ID", "0"))
LANES, NB, CHUNK, HDR = 8, 1024, 128, 26
SIGMA_OP = round(49.4 * 32)


def be(v: int, n: int) -> bytes:
    return v.to_bytes(n, "big")


def config(sigma: int, n_words: int, seeds: list[prng.Seed258]) -> bytes:
    return b"\x01" + be(sigma, 3) + be(n_words, 8) + b"".join(be(w, 8) for s in seeds for w in s)


def model_hist(seeds: list[prng.Seed258], sigma: int, n_words: int) -> np.ndarray:
    w = prng.lfsr258_words(n_words, seeds)  # (n_words, lanes)
    out = np.zeros((LANES, NB), dtype=np.int64)
    for lane in range(LANES):
        n = noise.noise(w[:, lane], TB, sigma)
        out[lane] = np.bincount(np.clip(n, -512, 511) + 512, minlength=NB)
    return out


class Port(UdpPort):
    async def cmd(self, data: bytes) -> dict[str, int | bytes]:
        await self.send(data)
        r = await self.recv()
        assert len(r) >= HDR, f"short reply {len(r)}"
        f = r[2]
        st: dict[str, int | bytes] = {
            "op": r[0], "code": r[1], "running": f & 1, "clearing": (f >> 1) & 1,
            "configured": (f >> 2) & 1, "reached": (f >> 3) & 1, "drained": (f >> 4) & 1,
            "words": int.from_bytes(r[3:11], "big"), "runlen": int.from_bytes(r[11:19], "big"),
            "sigma": int.from_bytes(r[19:22], "big"), "build": int.from_bytes(r[22:26], "big"),
            "len": len(r), "payload": r[HDR:],
        }  # fmt: skip
        assert st["build"] == BUILD_ID
        return st


async def until(port: Port, key: str, val: int, tries: int = 400) -> dict[str, int | bytes]:
    for _ in range(tries):
        st = await port.cmd(b"\x05")
        if st[key] == val:
            return st
    raise AssertionError(f"STATUS {key} never became {val}")


async def read_all(port: Port) -> np.ndarray:
    out = np.zeros((LANES, NB), dtype=np.int64)
    for lane in range(LANES):
        for c in range(NB // CHUNK):
            st = await port.cmd(bytes([4, lane, c]))
            while st["code"] == 1:  # not drained yet: the host retries
                st = await port.cmd(bytes([4, lane, c]))
            assert st["code"] == 0 and st["op"] == 0x84
            p = st["payload"]
            assert isinstance(p, bytes) and len(p) == 2 + CHUNK * 6 and p[:2] == bytes([lane, c])
            for b in range(CHUNK):
                out[lane, c * CHUNK + b] = int.from_bytes(p[2 + 6 * b : 8 + 6 * b], "big")
    return out


def assert_hist(got: np.ndarray, want: np.ndarray, what: str) -> None:
    bad = np.argwhere(got != want)
    assert len(bad) == 0, f"{what}: {len(bad)} bins differ, first (lane, bin): {bad[:4].tolist()}"


async def start(dut) -> Port:  # type: ignore[no-untyped-def]
    rng = get_rng("test_noise_hist_core")
    for s in ("s_tvalid_i", "s_tlast_i", "s_tuser_i", "m_tready_i", "s_tdata_i"):
        getattr(dut, s).value = 0
    dut.rst_i.value = 1
    cocotb.start_soon(Clock(dut.clk_i, 8, unit="ns").start())
    for _ in range(3):
        await FallingEdge(dut.clk_i)
    dut.rst_i.value = 0
    return Port(dut, rng)


@cocotb.test()
async def test_protocol_errors(dut) -> None:  # type: ignore[no-untyped-def]
    port = await start(dut)
    seeds = prng.lane_seeds(7, LANES)
    st = await port.cmd(b"\x05")
    assert st["code"] == 0 and st["op"] == 0x85 and not st["configured"] and st["len"] == HDR
    assert (await port.cmd(b"\x42"))["op"] == 0xFF
    assert (await port.cmd(b"\x42"))["code"] == 4
    cfg = config(SIGMA_OP, 10, seeds)
    for bad in (b"\x05\x00", b"\x02\x00", b"\x03\x00", b"\x04\x00", b"\x04\x00\x00\x00",
                cfg[:-1], cfg + b"\x00"):  # fmt: skip
        st = await port.cmd(bad)
        assert st["code"] == 2 and st["op"] == bad[0] | 0x80, f"length {len(bad)} op {bad[0]}"
    assert (await port.cmd(b"\x02"))["code"] == 1  # START before CONFIG
    bad_seed = [list(s) for s in seeds]
    bad_seed[5][3] = 1  # y4 needs a bit at or above 2^17
    st = await port.cmd(config(SIGMA_OP, 10, [tuple(s) for s in bad_seed]))  # type: ignore[misc]
    assert st["code"] == 3 and not st["configured"]
    assert (await port.cmd(config(1 << 17, 10, seeds)))["code"] == 3
    assert not (await port.cmd(b"\x05"))["configured"]
    st = await port.cmd(config(SIGMA_OP, 10, seeds))
    assert st["code"] == 0 and st["configured"] and st["runlen"] == 10 and st["sigma"] == SIGMA_OP
    await until(port, "clearing", 0)
    assert (await port.cmd(bytes([4, 8, 0])))["code"] == 3  # lane out of range
    assert (await port.cmd(bytes([4, 0, 8])))["code"] == 3  # chunk out of range
    # truncated datagram: no reply, next command answered normally
    await port.send(b"\x05", truncated=True)
    assert (await port.cmd(b"\x05"))["op"] == 0x85


@cocotb.test()
async def test_histograms_match_model(dut) -> None:  # type: ignore[no-untyped-def]
    port = await start(dut)
    rng = port.rng

    # 1. unbroken run of exactly N words
    seeds, n_words = prng.lane_seeds(rng.getrandbits(64), LANES), 300
    assert (await port.cmd(config(SIGMA_OP, n_words, seeds)))["code"] == 0
    await until(port, "clearing", 0)
    assert (await port.cmd(b"\x02"))["running"]
    st = await until(port, "reached", 1)
    assert st["words"] == n_words and not st["running"]
    assert (await port.cmd(b"\x02"))["code"] == 1  # N reached: START refused
    assert_hist(await read_all(port), model_hist(seeds, SIGMA_OP, n_words), "unbroken run")

    # 2. paused and resumed: same stream, same histogram; READ refused while running
    seeds, n_words = prng.lane_seeds(rng.getrandbits(64), LANES), 2000
    assert (await port.cmd(config(SIGMA_OP, n_words, seeds)))["code"] == 0
    await until(port, "clearing", 0)
    for _ in range(3):
        assert (await port.cmd(b"\x02"))["code"] == 0
        assert (await port.cmd(bytes([4, 0, 0])))["code"] == 1  # running
        st = await port.cmd(b"\x03")
        assert st["code"] == 0 and not st["running"] and 0 < st["words"] < n_words
    assert (await port.cmd(b"\x02"))["code"] == 0
    st = await until(port, "reached", 1)
    assert st["words"] == n_words
    assert_hist(await read_all(port), model_hist(seeds, SIGMA_OP, n_words), "pause/resume")

    # 3. max sigma: both clamp edges, CONFIG clears the previous counts
    seeds, n_words = prng.lane_seeds(rng.getrandbits(64), LANES), 400
    assert (await port.cmd(config((1 << 17) - 1, n_words, seeds)))["code"] == 0
    await until(port, "clearing", 0)
    await port.cmd(b"\x02")
    await until(port, "reached", 1)
    want = model_hist(seeds, (1 << 17) - 1, n_words)
    assert (want[:, 0] > 0).all() and (want[:, -1] > 0).all()
    assert_hist(await read_all(port), want, "max sigma, clamped")


@cocotb.test()
async def test_read_waits_for_drain(dut) -> None:  # type: ignore[no-untyped-def]
    """A run ends on its own while the host polls READ back to back with no handshake gaps.
    The first accepted READ must already hold the last words' samples, which are still in
    the noise_gen + hist_bram pipeline for ~17 clocks after the run gate drops (ADR 0009).
    sigma_reg = 1 puts nearly every sample in bin n = 0: the first bin of chunk 4 read out.
    N steps by 7 so the READ arrival phase sweeps the ~35-clock poll period."""
    port = await start(dut)
    port.p_valid = port.p_ready = 1.0
    for i in range(6):
        seeds, n_words, lane = prng.lane_seeds(port.rng.getrandbits(64), LANES), 64 + 7 * i, i
        assert (await port.cmd(config(1, n_words, seeds)))["code"] == 0
        await until(port, "clearing", 0)
        assert (await port.cmd(b"\x02"))["code"] == 0
        while (st := await port.cmd(bytes([4, lane, 4])))["code"] == 1:
            pass
        assert st["code"] == 0 and st["words"] == n_words and not st["running"]
        p = st["payload"]
        assert isinstance(p, bytes) and p[:2] == bytes([lane, 4])
        got = np.array([int.from_bytes(p[2 + 6 * b : 8 + 6 * b], "big") for b in range(CHUNK)])
        want = model_hist(seeds, 1, n_words)[lane, 4 * CHUNK : 5 * CHUNK]
        assert want[0] > n_words // 2, "sigma 1 should put most samples in bin n = 0"
        assert_hist(got[None, :], want[None, :], f"first READ after run {i} (N = {n_words})")
