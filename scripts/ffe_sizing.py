"""FFE length vs. performance, for the DSP sizing ADR (buildplan §7.5).

For each FFE length N (best pre-cursor split, 1-tap DFE, MMSE taps, float), find the input SNR
at which the reference RX reaches the target pre-FEC BER (Gaussian prediction at the slicer,
ideal DFE). The penalty vs. N = 32 is what shorter FFEs cost. Relative numbers only: DFE error
propagation is ignored here and affects every N similarly (model_ber_float.csv: 1.5x-4.4x).

Output: data/results/ffe_sizing.csv (sidecar: ffe_sizing.md).
"""

from __future__ import annotations

import csv
import subprocess
import sys
from pathlib import Path

import numpy as np
from scipy.optimize import brentq  # type: ignore[import-untyped]

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from model.equalizer import mmse_ffe_dfe  # noqa: E402
from model.link import noise_sigma  # noqa: E402
from model.stats import pam4_ber_awgn  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
CHANNELS = ["kr_ch2_19p3db", "kr_ch4_31p4db"]
N_TAPS = [4, 6, 8, 10, 12, 14, 16, 20, 24, 32]
TARGET_BER = 2.4e-4  # KP4 pre-FEC BER target used in 802.3ck/dj budgets [verify against 802.3dj]
REF_N = 32
MAX_PRE = 10  # pre-cursor taps searched 0..MAX_PRE


def slicer_snr(pulse: np.ndarray, cur: int, n: int, pre: int, snr_in: float) -> float:
    return mmse_ffe_dfe(pulse, cur, n, pre, 1, noise_sigma(pulse, snr_in) ** 2).snr_db


def required_snr(pulse: np.ndarray, cur: int, n: int, pre: int) -> float:
    """Input SNR (dB) at which the Gaussian-predicted BER equals TARGET_BER; inf if never."""
    def f(s: float) -> float:  # clamp: BER underflows to 0 at high SNR
        ber = max(pam4_ber_awgn(slicer_snr(pulse, cur, n, pre, s)), 1e-300)
        return float(np.log10(ber) - np.log10(TARGET_BER))

    if f(60.0) > 0:
        return float("inf")  # residual ISI floor above target
    return float(brentq(f, 0.0, 60.0, xtol=1e-4))


def main() -> None:
    commit = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, cwd=ROOT
    ).stdout.strip()
    rows = []
    for cid in CHANNELS:
        d = np.load(ROOT / "data" / "channels" / f"{cid}.npz")
        cur, n_pre, n_post = int(d["cursor"]), int(d["n_pre"]), int(d["n_post"])
        pulse = d["pulse"][cur - n_pre : cur + n_post + 1]
        best = {}
        for n in N_TAPS:
            cands = [(required_snr(pulse, n_pre, n, p), p) for p in range(0, min(n, MAX_PRE + 1))]
            best[n] = min(cands)
        ref = best[REF_N][0]
        for n in N_TAPS:
            req, pre = best[n]
            rows.append({
                "channel": cid, "ffe_taps": n, "best_pre": pre, "dfe_taps": 1,
                "target_ber": TARGET_BER, "required_input_snr_db": round(req, 3),
                "penalty_vs_32_db": round(req - ref, 3),
                "channel_taps": f"{n_pre}pre+{n_post}post", "commit": commit,
            })  # fmt: skip
            print(f"{cid} N={n:2d} pre={pre}: SNR_req {req:6.2f} dB, penalty {req - ref:5.2f} dB")
    with (ROOT / "data" / "results" / "ffe_sizing.csv").open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


if __name__ == "__main__":
    main()
