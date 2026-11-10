"""Host side of the hardware noise histogram (ADR 0009; protocol: docs/registers.md).

    noise_hist_run.py status
    noise_hist_run.py exact [--seed S]          # 2^22 words/lane, bin-for-bin vs the model
    noise_hist_run.py run   [--seed S] [--words N] [--checkpoint-s 3600]
    noise_hist_run.py run --attach              # resume checkpointing a run already going

Every command is safe to resend, so a lost datagram is retried. `run` pauses the board
(generator state is held, so the sample stream is unchanged), reads all 8 x 1024 bins, writes
the checkpoint and resumes. Results: data/results/noise_hist_{exact,hw}.csv + sidecar .md.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import socket
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from model import noise, prng  # noqa: E402

BOARD = ("192.168.10.2", 26400)
LANES, NB, CHUNK, HDR = 8, 1024, 128, 26
SIGMA_REG = round(49.4 * 32)  # Ch4 1e-12 operating point (ADR 0005)
RESULTS = ROOT / "data/results"
STATE = RESULTS / "noise_hist_hw.state.json"


class Board:
    def __init__(self, timeout: float = 0.5, retries: int = 20) -> None:
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("", 0))
        self.sock.settimeout(timeout)
        self.retries = retries

    def cmd(self, payload: bytes) -> dict[str, int | bytes]:
        for _ in range(self.retries):
            self.sock.sendto(payload, BOARD)
            try:
                while True:
                    r, src = self.sock.recvfrom(2048)
                    if src[0] == BOARD[0] and len(r) >= HDR and r[0] in (payload[0] | 0x80, 0xFF):
                        return parse(r)
            except TimeoutError:
                continue
        raise RuntimeError(f"no reply to op {payload[0]:#04x} after {self.retries} tries")

    def ok(self, payload: bytes) -> dict[str, int | bytes]:
        st = self.cmd(payload)
        if st["code"] != 0:
            raise RuntimeError(f"op {payload[0]:#04x} refused: code {st['code']}, {st}")
        return st

    def wait(self, key: str, val: int, poll_s: float = 0.2) -> dict[str, int | bytes]:
        while True:
            st = self.cmd(b"\x05")
            if st[key] == val:
                return st
            time.sleep(poll_s)

    def read_all(self) -> np.ndarray:
        out = np.zeros((LANES, NB), dtype=np.int64)
        for lane in range(LANES):
            for c in range(NB // CHUNK):
                while (st := self.cmd(bytes([4, lane, c])))["code"] == 1:
                    time.sleep(0.01)  # not drained yet
                p = st["payload"]
                assert st["code"] == 0 and isinstance(p, bytes) and p[:2] == bytes([lane, c])
                b = np.frombuffer(p[2:], dtype=np.uint8).reshape(CHUNK, 6).astype(np.int64)
                out[lane, c * CHUNK : (c + 1) * CHUNK] = b @ (256 ** np.arange(5, -1, -1))
        return out


def parse(r: bytes) -> dict[str, int | bytes]:
    f = r[2]
    return {
        "op": r[0], "code": r[1], "running": f & 1, "clearing": (f >> 1) & 1,
        "configured": (f >> 2) & 1, "reached": (f >> 3) & 1, "drained": (f >> 4) & 1,
        "words": int.from_bytes(r[3:11], "big"), "runlen": int.from_bytes(r[11:19], "big"),
        "sigma": int.from_bytes(r[19:22], "big"), "build": int.from_bytes(r[22:26], "big"),
        "payload": r[HDR:],
    }  # fmt: skip


def config_cmd(sigma: int, n_words: int, seeds: list[prng.Seed258]) -> bytes:
    body = b"".join(w.to_bytes(8, "big") for s in seeds for w in s)
    return b"\x01" + sigma.to_bytes(3, "big") + n_words.to_bytes(8, "big") + body


def model_hist(seeds: list[prng.Seed258], sigma: int, n_words: int) -> np.ndarray:
    tb = noise.build_tables(noise.NoiseCfg())
    w = prng.lfsr258_words(n_words, seeds)
    out = np.zeros((LANES, NB), dtype=np.int64)
    for lane in range(LANES):
        n = noise.noise(w[:, lane], tb, sigma)
        out[lane] = np.bincount(np.clip(n, -512, 511) + 512, minlength=NB)
    return out


def write_csv(path: Path, cols: dict[str, np.ndarray]) -> None:
    with path.open("w", newline="") as fh:
        wr = csv.writer(fh)
        wr.writerow(["lane", "n", *cols])
        for lane in range(LANES):
            for b in range(NB):
                wr.writerow([lane, b - NB // 2, *(int(v[lane, b]) for v in cols.values())])


def sidecar(path: Path, cmd: str, st: dict[str, int | bytes], meta: dict[str, object]) -> None:
    commit = subprocess.run(["git", "rev-parse", "--short=8", "HEAD"], capture_output=True,
                            text=True, cwd=ROOT).stdout.strip()  # fmt: skip
    lines = [f"# {path.name}", "", f"- Written: {dt.datetime.now().isoformat(timespec='seconds')}",
             f"- Command: `{cmd}`", f"- Host commit: {commit}",
             f"- Bitstream build id: {int(st['build']):08x}", f"- sigma_reg: {st['sigma']}",
             f"- Words per lane: {st['words']} (run length {st['runlen']})",
             *(f"- {k}: {v}" for k, v in meta.items()),
             "- Columns: lane, n (bin = clamp(n, -512, 511)), counts", "",
             "Interpretation: see analysis/noise_hist.py output and docs/log.md."]  # fmt: skip
    path.with_suffix(".md").write_text("\n".join(lines) + "\n")


def configure(bd: Board, seed: int, n_words: int) -> list[prng.Seed258]:
    seeds = prng.lane_seeds(seed, LANES)
    bd.cmd(b"\x03")  # stop anything running
    bd.ok(config_cmd(SIGMA_REG, n_words, seeds))
    bd.wait("clearing", 0)
    return seeds


def exact(bd: Board, seed: int) -> int:
    n_words = 1 << 22
    seeds = configure(bd, seed, n_words)
    t0 = time.time()
    bd.ok(b"\x02")
    st = bd.wait("reached", 1)
    hw = bd.read_all()
    print(f"board: {n_words} words/lane in {time.time() - t0:.1f} s; computing the model ...")
    want = model_hist(seeds, SIGMA_REG, n_words)
    out = RESULTS / "noise_hist_exact.csv"
    write_csv(out, {"hw": hw, "model": want})
    diff = int(np.count_nonzero(hw != want))
    sidecar(out, " ".join(sys.argv), st, {"seed (lane_seeds)": seed, "bins differing": diff,
                                          "verdict": "PASS" if diff == 0 else "FAIL"})  # fmt: skip
    assert int(hw.sum()) == LANES * n_words == int(want.sum())
    print(f"{'PASS' if diff == 0 else 'FAIL'}: {diff} of {LANES * NB} bins differ -> {out}")
    return 0 if diff == 0 else 1


def run(bd: Board, seed: int, n_words: int, period: float, attach: bool) -> int:
    out = RESULTS / "noise_hist_hw.csv"
    if attach:
        state = json.loads(STATE.read_text())
    else:
        configure(bd, seed, n_words)
        state = {"seed": seed, "words_target": n_words, "started": time.time()}
        STATE.write_text(json.dumps(state))
        bd.ok(b"\x02")
    while True:
        time.sleep(period)
        bd.ok(b"\x03")  # pause: generator state held
        hist = bd.read_all()
        st = bd.cmd(b"\x05")
        if int(hist.sum()) != LANES * int(st["words"]):
            raise RuntimeError(f"bins sum {hist.sum()} != 8 x words {st['words']}")
        write_csv(out, {"count": hist})
        elapsed_h = (time.time() - state["started"]) / 3600
        sidecar(out, " ".join(sys.argv), st,
                {"seed (lane_seeds)": state["seed"], "elapsed_h": f"{elapsed_h:.2f}"})
        print(f"{dt.datetime.now():%H:%M:%S} checkpoint: {st['words']} words/lane "
              f"({100 * int(st['words']) / int(state['words_target']):.1f}%)", flush=True)
        if st["reached"]:
            print("run complete")
            return 0
        bd.ok(b"\x02")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["status", "exact", "run"])
    ap.add_argument("--seed", type=int, default=0x5EED0005)
    ap.add_argument("--words", type=int, default=5 * 10**12)  # x 8 lanes = 4e13 (ADR 0003)
    ap.add_argument("--checkpoint-s", type=float, default=3600.0)
    ap.add_argument("--attach", action="store_true")
    a = ap.parse_args()
    bd = Board()
    if a.mode == "status":
        st = bd.cmd(b"\x05")
        print({k: v for k, v in st.items() if k != "payload"} | {"build": f"{st['build']:08x}"})
        return 0
    if a.mode == "exact":
        return exact(bd, a.seed)
    return run(bd, a.seed, a.words, a.checkpoint_s, a.attach)


if __name__ == "__main__":
    sys.exit(main())
