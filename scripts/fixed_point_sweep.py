"""Fixed-point sizing: ADC bits/full-scale, FFE coefficient and output widths (fixed-point ADR).

Metric: slicer SNR penalty of the integer receiver (model/fixed.py) vs. a float receiver on the
SAME symbols, noise and quantized channel, ideal-decision DFE (error propagation is measured
separately). Slicer SNR = E[a^2] / E[e^2], e = (z - b*a[k-1]) / h0 - a[k].

Evaluated at two operating points per channel: the input SNR where the float receiver's
Gaussian-predicted BER is 2.4e-4 and where it is 1e-12. Quantization noise is fixed while
channel noise shrinks, so the low-BER point is the one that sizes the datapath.

One factor at a time; the others held at generous values (GEN). Then the chosen config
(FixedCfg defaults, ADR 0004) with real DFE decisions: BER float vs. fixed on the same samples.
Output: data/results/fixed_point_{sweep,ber}.csv (sidecars .md).
"""

from __future__ import annotations

import csv
import math
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import numpy as np
from scipy.optimize import brentq  # type: ignore[import-untyped]

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from model import fixed as fx  # noqa: E402
from model.equalizer import PAM4_ES, mmse_ffe_dfe  # noqa: E402
from model.fixed import FixedCfg  # noqa: E402
from model.link import dfe1_decide, noise_sigma  # noqa: E402
from model.pam4 import LEVELS, bits_to_symbols, symbols_to_bits  # noqa: E402
from model.stats import clopper_pearson, pam4_ber_awgn  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
CHANNELS = ["kr_ch2_19p3db", "kr_ch4_31p4db"]
N_TAPS, N_PRE = 16, 4  # ADR 0002
TARGETS = [2.4e-4, 1e-12]
N_SYM = 1_000_000
N_SYM_BER = 5_000_000
BER_OFFSETS_DB = [0.0, 1.0, 2.0]  # above the 2.4e-4 operating point
SEED_DATA, SEED_NOISE = 101, 202


GEN = FixedCfg(adc_bits=12, clip=4.0, frac=8, coef_bits=18, out_bits=20)  # 'no quantization'


def float_required_snr(pulse: np.ndarray, cur: int, ber: float) -> float:
    def f(s: float) -> float:
        eq = mmse_ffe_dfe(pulse, cur, N_TAPS, N_PRE, 1, noise_sigma(pulse, s) ** 2)
        return math.log10(max(pam4_ber_awgn(eq.snr_db), 1e-300)) - math.log10(ber)

    return float(brentq(f, 0.0, 60.0, xtol=1e-4))


def operating_point(pulse: np.ndarray, cur: int, snr_db: float, c: FixedCfg, n_sym: int) -> dict:
    """Shared stimulus for paired float/fixed receivers on the (quantized) emulator channel."""
    hq = fx.channel_int(pulse, c)
    h = hq.astype(np.float64)  # float reference uses the same quantized channel
    sigma = noise_sigma(h, snr_db)
    rng_d = np.random.default_rng(SEED_DATA)
    rng_n = np.random.default_rng(np.random.SeedSequence(SEED_NOISE, spawn_key=(1,)))
    a = bits_to_symbols(rng_d.integers(0, 2, 2 * n_sym, dtype=np.uint8))
    s = np.convolve(a, hq)[cur : cur + n_sym]
    n = rng_n.normal(0.0, sigma, n_sym)
    eq = mmse_ffe_dfe(h, cur, N_TAPS, N_PRE, 1, sigma**2)
    regs = fx.rx_regs(hq, cur, eq.taps, N_PRE, c)
    g = len(h) + N_TAPS
    sl = slice(g, n_sym - g)
    z_f = np.convolve(s + n, eq.taps)[N_PRE : N_PRE + n_sym][sl]
    x = fx.adc(s + np.round(n).astype(np.int64), c.frac, c.adc_bits)
    z_i = fx.ffe_out(x, regs, N_PRE, c)[sl]
    return {"a": a, "sl": sl, "g": g, "eq": eq, "regs": regs, "z_f": z_f, "z_i": z_i, "x": x,
            "h": h}  # fmt: skip


def measure(pulse: np.ndarray, cur: int, snr_db: float, c: FixedCfg) -> dict[str, float]:
    """Paired float vs. fixed slicer SNR on N_SYM symbols, ideal-decision DFE."""
    o = operating_point(pulse, cur, snr_db, c, N_SYM)
    a, g, eq, r = o["a"], o["g"], o["eq"], o["regs"]
    a_now, a_prev = a[o["sl"]], a[g - 1 : N_SYM - g - 1]
    e_f = (o["z_f"] - eq.dfe[0] * a_prev) / eq.h0 - a_now
    e_i = (o["z_i"] - r.dfe_b * a_prev) / (r.t2 / 2) - a_now
    snr_f = 10 * math.log10(PAM4_ES / float(np.mean(e_f**2)))
    snr_i = 10 * math.log10(PAM4_ES / float(np.mean(e_i**2)))
    h = o["h"]
    return {
        "snr_slicer_float_db": round(snr_f, 4),
        "snr_slicer_fixed_db": round(snr_i, 4),
        "penalty_db": round(snr_f - snr_i, 4),
        "adc_clip_rate": float(np.mean(np.abs(o["x"]) == (1 << (c.adc_bits - 1)) - 1)),
        "ffe_out_sat_rate": float(np.mean(np.abs(o["z_i"]) == (1 << (c.out_bits - 1)) - 1)),
        "peak_over_rms": round(3 * float(np.sum(np.abs(h))) / math.sqrt(PAM4_ES * float(h @ h)), 3),
        "out_shift": r.out_shift,
        "h0_z": r.t2 / 2,
    }  # fmt: skip


def sweeps() -> list[tuple[str, FixedCfg]]:
    out: list[tuple[str, FixedCfg]] = [("reference", GEN), ("chosen", FixedCfg())]
    for bits in (5, 6, 7, 8):
        for clip in (1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 5.0):
            out.append(("adc", replace(GEN, adc_bits=bits, clip=clip)))
    for frac in (0, 1, 2, 3, 4, 6):
        out.append(("frac", replace(GEN, adc_bits=7, clip=3.0, frac=frac)))
    for cb in (6, 7, 8, 9, 10, 11, 12, 14):
        out.append(("coef", replace(GEN, coef_bits=cb)))
    for ob in (6, 7, 8, 9, 10, 11, 12, 14):
        out.append(("out", replace(GEN, out_bits=ob)))
    return out


def ber_pair(pulse: np.ndarray, cur: int, snr_db: float) -> dict[str, float]:
    """Real-decision DFE BER, float vs. chosen fixed config, same symbols and noise."""
    c = FixedCfg()
    o = operating_point(pulse, cur, snr_db, c, N_SYM_BER)
    a, g, eq, r, sl = o["a"], o["g"], o["eq"], o["regs"], o["sl"]
    idx = (a + 3) // 2
    d0 = int(idx[g - 1])
    tb = symbols_to_bits(a[sl])
    out: dict[str, float] = {}
    for name, d in (
        ("float", dfe1_decide(o["z_f"], float(eq.dfe[0]), eq.h0, d0)),
        ("fixed", dfe1_decide(o["z_i"].astype(np.float64), float(r.dfe_b), r.t2 / 2, d0)),
    ):
        rb = symbols_to_bits(LEVELS[d])
        errs = int(np.count_nonzero(rb != tb))
        lo, hi = clopper_pearson(errs, len(tb))
        out |= {f"{name}_bit_errors": errs, f"{name}_ber": errs / len(tb),
                f"{name}_ber_lo95": lo, f"{name}_ber_hi95": hi}  # fmt: skip
    out["bits"] = len(tb)
    out["fixed_over_float"] = round(out["fixed_ber"] / max(out["float_ber"], 1e-300), 3)
    return out


def main() -> None:
    commit = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, cwd=ROOT
    ).stdout.strip()
    rows, ber_rows = [], []
    for cid in CHANNELS:
        d = np.load(ROOT / "data" / "channels" / f"{cid}.npz")
        cur, n_pre, n_post = int(d["cursor"]), int(d["n_pre"]), int(d["n_post"])
        pulse = d["pulse"][cur - n_pre : cur + n_post + 1]
        snr0 = float_required_snr(pulse, n_pre, TARGETS[0])
        for off in BER_OFFSETS_DB:
            b = ber_pair(pulse, n_pre, snr0 + off)
            ber_rows.append({"channel": cid, "input_snr_db": round(snr0 + off, 3), **b,
                             **FixedCfg().__dict__, "n_sym": N_SYM_BER, "seed_data": SEED_DATA,
                             "seed_noise": SEED_NOISE, "commit": commit})  # fmt: skip
            print(f"{cid} SNR {snr0 + off:.2f}: float {b['float_bit_errors']} / fixed "
                  f"{b['fixed_bit_errors']} errors of {b['bits']} bits")  # fmt: skip
        for ber in TARGETS:
            snr_in = float_required_snr(pulse, n_pre, ber)
            for sweep, c in sweeps():
                m = measure(pulse, n_pre, snr_in, c)
                rows.append({"channel": cid, "target_ber": ber, "input_snr_db": round(snr_in, 3),
                             "sweep": sweep, **c.__dict__, **m, "n_sym": N_SYM,
                             "seed_data": SEED_DATA, "seed_noise": SEED_NOISE,
                             "commit": commit})  # fmt: skip
                print(f"{cid} {ber:.0e} {sweep:9s} {c} pen {m['penalty_db']:+.3f} dB "
                      f"clip {m['adc_clip_rate']:.1e}")  # fmt: skip
    for name, rr in (("fixed_point_sweep", rows), ("fixed_point_ber", ber_rows)):
        with (ROOT / "data" / "results" / f"{name}.csv").open("w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rr[0]))
            w.writeheader()
            w.writerows(rr)


if __name__ == "__main__":
    main()
