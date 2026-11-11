"""Host side of the hardware BER board (ADR 0012; protocol: docs/registers.md, port 26401).

    ber_run.py status
    ber_run.py exact --channel kr_ch4_31p4db --snr 21 [--precoder] [--cw 200] [--seed S]
    ber_run.py sweep --channel kr_ch4_31p4db --snr 22,23,24 --bits 1e10 [--precoder] [--seed S]
    ber_run.py model --channel kr_ch4_31p4db [--precoder] [--max-model-bits 1.2e8]  # no board

`exact`: a run of R bits on the board vs the bit-exact model (same seeds, same R): bit errors,
symbol errors and bits must be equal. `sweep`: one fixed-length run per SNR point (R chosen in
advance, never stopped on an error count, so the estimate is unbiased), with a 95%
Clopper-Pearson interval; fewer than 100 errors is reported as an upper bound (CLAUDE.md §10).
The equalizer is the MMSE FFE + 1-tap DFE designed at the point's SNR (model.equalizer),
quantized by model.fixed.rx_regs. SNR = PAM4 Es * sum(hq^2) / sigma^2 (model.link.noise_sigma)
on the quantized channel; sigma_reg = round(32 sigma) (docs/fixed-point.md).
Results: data/results/ber_exact_<channel>[_pre].csv, data/results/ber_hw_<channel>[_pre].csv,
sidecars .md.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import math
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from scipy.stats import t as student_t  # type: ignore[import-untyped]

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from model import fixed as fx  # noqa: E402
from model import noise, prng, rs, rx, tx  # noqa: E402
from model.equalizer import mmse_ffe_dfe  # noqa: E402
from model.link import noise_sigma  # noqa: E402
from model.stats import clopper_pearson  # noqa: E402

BOARD = ("192.168.10.2", 26401)
HDR = 39
P, L, N, N_PRE = 4, 16, 16, 4  # ber_top (ADR 0002)
M0 = P * math.ceil((L + N - 2) / P)
HOLDOFF = 64  # RX words: DFE start-up burst from the d_init guess (ADR 0011 note: >= 10 symbols)
SIGMA_FRAC = noise.NoiseCfg().sigma_frac
CFG = fx.FixedCfg()
RESULTS = ROOT / "data/results"
MIN_CHUNKS = 20  # independent model runs per point (batch-means CI)


class Board:
    def __init__(self, timeout: float = 0.5, retries: int = 20) -> None:
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("", 0))
        self.sock.settimeout(timeout)
        self.retries = retries

    def cmd(self, payload: bytes) -> dict[str, int]:
        """Every command is safe to resend except START (a new run): the caller checks."""
        for _ in range(self.retries):
            self.sock.sendto(payload, BOARD)
            try:
                while True:
                    r, src = self.sock.recvfrom(2048)
                    if src[0] == BOARD[0] and len(r) == HDR and r[0] in (payload[0] | 0x80, 0xFF):
                        return parse(r)
            except TimeoutError:
                continue
        raise RuntimeError(f"no reply to op {payload[0]:#04x} after {self.retries} tries")

    def ok(self, payload: bytes) -> dict[str, int]:
        st = self.cmd(payload)
        if st["code"] != 0:
            raise RuntimeError(f"op {payload[0]:#04x} refused: code {st['code']}, {st}")
        return st


def parse(r: bytes) -> dict[str, int]:
    f = r[2]
    return {
        "op": r[0], "code": r[1], "running": f & 1, "configured": (f >> 1) & 1,
        "reached": (f >> 2) & 1, "fifo_err": (f >> 3) & 1,
        "bits": int.from_bytes(r[3:11], "big"), "bit_err": int.from_bytes(r[11:19], "big"),
        "sym_err": int.from_bytes(r[19:27], "big"), "runlen": int.from_bytes(r[27:35], "big"),
        "build": int.from_bytes(r[35:39], "big"),
    }  # fmt: skip


def be(v: int, n: int) -> bytes:
    return (v & ((1 << (8 * n)) - 1)).to_bytes(n, "big")


@dataclass
class Point:
    """One board configuration: channel, SNR, equalizer registers, seeds."""

    channel: str
    snr_db: float
    precoder: bool
    hq: list[int]
    cursor: int
    regs: fx.RxRegs
    sigma_reg: int
    prbs_seed: int
    noise_seed: int  # model.prng.lane_seeds(noise_seed, P)

    @property
    def lag(self) -> int:
        return self.cursor + N_PRE

    def config(self, r: int) -> bytes:
        seeds = prng.lane_seeds(self.noise_seed, P)
        taps = self.hq + [0] * (L - len(self.hq))
        return (b"\x01" + be(r, 8) + be(self.prbs_seed, 4) + be(int(self.precoder), 1)
                + be(self.sigma_reg, 3) + be(self.lag, 1) + be(HOLDOFF, 2)
                + be(self.regs.out_shift, 1) + be(int(self.regs.dfe_b), 2)
                + be(int(self.regs.t2), 2)
                + b"".join(be(t, 2) for t in taps)
                + b"".join(be(int(c), 2) for c in self.regs.coefs)
                + b"".join(be(w, 8) for s in seeds for w in s))  # fmt: skip


def point(channel: str, snr_db: float, precoder: bool, seed: int) -> Point:
    d = np.load(ROOT / f"data/channels/{channel}.npz")
    c, a0, a1 = int(d["cursor"]), int(d["n_pre"]), int(d["n_post"])
    hq = fx.channel_int(d["pulse"][c - a0 : c + a1 + 1], CFG)
    h = hq.astype(np.float64)
    sigma = noise_sigma(h, snr_db)  # pre-ADC units, same as hq
    eq = mmse_ffe_dfe(h, a0, N, N_PRE, 1, sigma**2)
    rng = np.random.default_rng(seed)
    regs = fx.rx_regs(hq, a0, eq.taps, N_PRE, CFG)
    return Point(channel, snr_db, precoder, hq.tolist(), a0, regs,
                 round(sigma * (1 << SIGMA_FRAC)), int(rng.integers(1, 1 << 31)),
                 int(rng.integers(0, 1 << 63)))  # fmt: skip


_TB: list[noise.Tables] = []


def model_counts(pt: Point, n_cw: int) -> tuple[rx.ErrCount, int]:
    """Bit-exact model over n_cw codewords: (counts over R bits, R), R the longest the model
    covers, a multiple of 2P (test_ber_core's frame)."""
    if not _TB:
        _TB.append(noise.build_tables(noise.NoiseCfg()))  # ~25 s, once per process
    tb = _TB[0]
    t = tx.tx(n_cw, pt.prbs_seed, pt.precoder)
    seeds = prng.lane_seeds(pt.noise_seed, P)
    y = tx.pre_adc(t.a, np.array(pt.hq, dtype=np.int64), pt.cursor, seeds, tb, pt.sigma_reg)
    x_hw = tx.front_end(y, CFG)[tx.valid(len(t.a), L, pt.cursor)]
    out = rx.rx(x_hw, pt.regs, CFG, pt.precoder, d_init=0, p_init=0, start=M0 - (L - 1))
    words = min(len(out.gray) // P, (len(t.gray) - (M0 - pt.lag)) // P) - HOLDOFF
    n_sym = (HOLDOFF + words) * P
    c = rx.count_errors(out.gray[:n_sym], t.gray, M0 - pt.lag, HOLDOFF * P)
    return c, 2 * P * words


def commit() -> str:
    return subprocess.run(["git", "rev-parse", "--short=8", "HEAD"], capture_output=True,
                          text=True, cwd=ROOT).stdout.strip()  # fmt: skip


def run_r(bd: Board, pt: Point, r: int, poll_s: float = 1.0) -> dict[str, int]:
    """CONFIG with R, START once (a resent START would restart the run), wait for R."""
    bd.cmd(b"\x03")  # stop anything running
    bd.ok(pt.config(r))
    st = bd.ok(b"\x02")
    if not st["running"]:
        raise RuntimeError(f"START accepted but not running: {st}")
    t0 = time.time()
    while not (st := bd.cmd(b"\x05"))["reached"]:
        if not st["running"]:
            raise RuntimeError(f"run ended before R: {st}")
        if time.time() - t0 > 10:
            print(f"  {st['bits'] / r:6.1%}  {st['bit_err']} bit errors", end="\r", flush=True)
        time.sleep(poll_s)
    if st["fifo_err"]:
        raise RuntimeError(f"BER FIFO error: run void {st}")
    return st


ROW = ["channel", "precoder", "snr_db", "sigma_reg", "lag", "holdoff",
       "prbs_seed", "noise_seed", "bits", "bit_errors", "sym_errors", "ber", "ci95_lo",
       "ci95_hi", "kind", "build_id"]  # fmt: skip


def row(pt: Point, st: dict[str, int]) -> list[object]:
    bits, e = st["bits"], st["bit_err"]
    lo, hi = clopper_pearson(e, bits)
    kind = "estimate" if e >= 100 else "upper_bound"
    return [pt.channel, int(pt.precoder), pt.snr_db, pt.sigma_reg, pt.lag, HOLDOFF,
            pt.prbs_seed, pt.noise_seed, bits, e, st["sym_err"], e / bits, lo, hi, kind,
            f"{st['build']:08x}"]  # fmt: skip


def sidecar(path: Path, meta: dict[str, object], interp: str) -> None:
    lines = [f"# {path.name}", "", f"- Written: {dt.datetime.now().isoformat(timespec='seconds')}",
             f"- Command: `{' '.join(sys.argv)}`", f"- Host commit: {commit()}",
             *(f"- {k}: {v}" for k, v in meta.items()),
             "- SNR: PAM4 Es * sum(hq^2) / sigma^2 on the quantized channel "
             "(model.link.noise_sigma)",
             "- Equalizer: MMSE FFE 16 taps (4 pre) + 1-tap DFE designed at the point's SNR, "
             "fixed point per ADR 0004; holdoff and lag per ADR 0011; interleaving: none (pre-FEC)",
             "- CI: 95% Clopper-Pearson; kind = upper_bound when fewer than 100 bit errors", "",
             f"Interpretation: {interp}"]  # fmt: skip
    path.with_suffix(".md").write_text("\n".join(lines) + "\n")


def check_build(st: dict[str, int]) -> None:
    head = commit()
    if f"{st['build']:08x}" != head:
        print(f"WARNING: bitstream build {st['build']:08x} != host HEAD {head}")


def exact(bd: Board, a: argparse.Namespace) -> int:
    pt = point(a.channel, a.snr, a.precoder, a.seed)
    print(f"model: {a.cw} codewords at {a.snr} dB (sigma_reg {pt.sigma_reg}) ...")
    want, r = model_counts(pt, a.cw)
    st = run_r(bd, pt, r)
    check_build(st)
    got = rx.ErrCount(st["bits"], st["bit_err"], st["sym_err"])
    ok = got == want
    out = RESULTS / f"ber_exact_{a.channel}{'_pre' if a.precoder else ''}.csv"
    with out.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["source", *ROW])
        w.writerow(["board", *row(pt, st)])
        w.writerow(["model", *row(pt, st | {"bits": want.bits, "bit_err": want.bit_errors,
                                            "sym_err": want.sym_errors})])  # fmt: skip
    sidecar(out, {"seed": a.seed, "codewords (model)": a.cw, "R (bits)": r,
                  "verdict": "PASS" if ok else "FAIL"},
            "ADR 0012 exactness check: the board's counts over exactly R bits vs the bit-exact "
            "model for the same seeds and registers. PASS means bits, bit errors and symbol "
            "errors are all equal, so long board runs sample the model's error "
            "process.")  # fmt: skip
    print(f"{'PASS' if ok else 'FAIL'}: board {got}, model {want} -> {out}")
    return 0 if ok else 1


def sweep(bd: Board, a: argparse.Namespace) -> int:
    r = int(float(a.bits)) // (2 * P) * (2 * P)
    out = RESULTS / f"ber_hw_{a.channel}{'_pre' if a.precoder else ''}.csv"
    rows = []
    for i, s in enumerate(float(v) for v in a.snr.split(",")):
        pt = point(a.channel, s, a.precoder, a.seed + i)
        t0 = time.time()
        st = run_r(bd, pt, r)
        check_build(st)
        rows.append(row(pt, st))
        print(f"{s:6.2f} dB  sigma_reg {pt.sigma_reg:6d}  {st['bit_err']:>12d} / {st['bits']:.3e}"
              f"  BER {st['bit_err'] / st['bits']:.3e}  ({time.time() - t0:.0f} s)")
        with out.open("w", newline="") as fh:  # rewrite after every point: a crash keeps them
            w = csv.writer(fh)
            w.writerow(ROW)
            w.writerows(rows)
        sidecar(out, {"seed (point i uses seed + i)": a.seed, "R per point (bits)": r},
                "pre-FEC BER measured on the board (ber_top), one fixed-length run per SNR. "
                "Compare with the bit-exact fixed-point model, never the float curve (ADR 0004).")
    return 0


def batch_ci(e: list[int], b: list[int], conf: float = 0.95) -> tuple[float, float]:
    """CI of sum(e) / sum(b) from independent chunks (ratio estimator, t on n - 1 dof).
    Unlike Clopper-Pearson it does not assume independent bit errors: DFE error bursts (and the
    precoder's paired errors) widen it. Needs >= 2 chunks."""
    ea, ba = np.asarray(e, dtype=np.float64), np.asarray(b, dtype=np.float64)
    n, r = len(ea), ea.sum() / ba.sum()
    se = math.sqrt(n / (n - 1) * float(((ea - r * ba) ** 2).sum())) / ba.sum()
    t = float(student_t.ppf(0.5 + conf / 2, n - 1))
    return max(0.0, r - t * se), r + t * se


def model(a: argparse.Namespace) -> int:
    """Bit-exact model at every point of a board sweep CSV, independent seeds (same channel,
    SNR, registers), in >= MIN_CHUNKS chunks, each with its own seeds and start-up, so the
    batch-means CI (batch_ci) is available. Length set from the board's BER for
    --model-errors expected errors, capped at --max-model-bits; a point needing more than the
    cap for 100 expected errors is not run (no row)."""
    name = f"{a.channel}{'_pre' if a.precoder else ''}"
    rows = list(csv.DictReader((RESULTS / f"ber_hw_{name}.csv").open()))
    out = RESULTS / f"ber_model_{name}.csv"
    cap, res, skipped = int(float(a.max_model_bits)), [], []
    cw_bits = rs.N * rs.M
    for i, hw in enumerate(rows):
        ber = int(hw["bit_errors"]) / int(hw["bits"])
        if 100 / ber > cap:
            skipped.append(hw["snr_db"])
            continue
        target = min(cap, math.ceil(a.model_errors / ber))
        n_cw = max(20, min(2000, math.ceil(target / MIN_CHUNKS / cw_bits)))
        pt = point(a.channel, float(hw["snr_db"]), a.precoder, a.seed + i)
        assert pt.sigma_reg == int(hw["sigma_reg"]), "SNR -> sigma_reg differs from the board run"
        rng = np.random.default_rng([a.seed, 0x30DE1, i])  # independent of the board's seeds
        es: list[int] = []
        bs: list[int] = []
        ss: list[int] = []
        t0 = time.time()
        while sum(bs) < target or len(bs) < MIN_CHUNKS:
            pt.prbs_seed = int(rng.integers(1, 1 << 31))
            pt.noise_seed = int(rng.integers(0, 1 << 63))
            c, _ = model_counts(pt, n_cw)
            es.append(c.bit_errors)
            bs.append(c.bits)
            ss.append(c.sym_errors)
        lo, hi = batch_ci(es, bs)
        res.append(row(pt, {"bits": sum(bs), "bit_err": sum(es), "sym_err": sum(ss),
                            "build": 0}) + [len(bs), lo, hi])  # fmt: skip
        print(f"{hw['snr_db']:>6} dB  model {sum(es)} / {sum(bs):.3e}  BER "
              f"{sum(es) / sum(bs):.3e} [{lo:.3e}, {hi:.3e}]  board {ber:.3e}  "
              f"({len(bs)} chunks, {time.time() - t0:.0f} s)", flush=True)  # fmt: skip
        with out.open("w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow([*ROW, "chunks", "ci95_lo_batch", "ci95_hi_batch"])
            w.writerows(res)
        sidecar(out, {"seed": a.seed, "target errors": a.model_errors, "bit cap per point": cap,
                      "not run (need > cap bits for 100 errors)": ", ".join(skipped) or "none",
                      "board sweep": f"ber_hw_{name}.csv"},
                "bit-exact fixed-point model (model.tx/rx, same registers as the board run, "
                "independent seeds per chunk; prbs/noise seed columns = the last chunk's). "
                "build_id 00000000 = model, not hardware. ci95_*_batch: batch means over the "
                "chunks (ratio estimator, Student t), valid with DFE error bursts; ci95_lo/hi: "
                "Clopper-Pearson, which assumes independent errors and is too narrow here. "
                "Compare the board with the batch CI (ADR 0004).")  # fmt: skip
    print("not run:", skipped or "none")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["status", "exact", "sweep", "model"])
    ap.add_argument("--channel", default="kr_ch4_31p4db")
    ap.add_argument("--snr", default="21")
    ap.add_argument("--precoder", action="store_true")
    ap.add_argument("--seed", type=int, default=0x5EED0012)
    ap.add_argument("--cw", type=int, default=200)
    ap.add_argument("--bits", default="1e10")
    ap.add_argument("--max-model-bits", default="1.2e8")
    ap.add_argument("--model-errors", type=int, default=3000)
    a = ap.parse_args()
    if a.mode == "model":
        return model(a)
    bd = Board()
    if a.mode == "status":
        st = bd.cmd(b"\x05")
        print(st | {"build": f"{st['build']:08x}"})
        return 0
    if a.mode == "exact":
        a.snr = float(a.snr)
        return exact(bd, a)
    return sweep(bd, a)


if __name__ == "__main__":
    sys.exit(main())
