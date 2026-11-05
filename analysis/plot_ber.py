"""Model BER waterfall (Phase A media). Run by `make plots` only."""

from __future__ import annotations

import csv
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
INK, MUTED, GRID, SURFACE = "#0b0b0b", "#52514e", "#e4e3df", "#fcfcfb"
REAL, IDEAL = "#2a78d6", "#eb6834"  # categorical slots 1, 2
SRC = ROOT / "data" / "results" / "model_ber_float.csv"
OUT = ROOT / "docs" / "media" / "2026-11-05_phase-a_model-ber-waterfall.png"
TITLES = {"kr_ch2_19p3db": "KR Ch2, 19.3 dB IL", "kr_ch4_31p4db": "KR Ch4, 31.4 dB IL"}


def f(x: str) -> float:
    return float(x) if x else np.nan


def main() -> None:
    if not SRC.exists():
        sys.exit(f"missing {SRC}; run `make model-ber` first")
    rows = list(csv.DictReader(SRC.open()))
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.4), sharey=True, facecolor=SURFACE)
    for ax, (cid, title) in zip(axes, TITLES.items(), strict=True):
        r = [x for x in rows if x["channel"] == cid]
        snr = np.array([f(x["snr_db"]) for x in r])
        cols = ("ber", "ber_ci95_lo", "ber_ci95_hi")
        ber, lo, hi = (np.array([f(x[k]) for x in r]) for k in cols)
        ub = np.array([f(x["ber_upper_bound95"]) for x in r])
        ide = np.array([f(x["ber_ideal_dfe"]) for x in r])
        ide_ub = np.array([f(x["ber_ideal_dfe_upper_bound95"]) for x in r])
        pred = np.array([f(x["ber_pred_gaussian"]) for x in r])
        b = f(r[0]["dfe_b_over_h0"])
        ax.set_facecolor(SURFACE)
        ax.plot(snr, pred, "--", color=MUTED, lw=1.5, label="Gaussian prediction (MMSE SNR)")
        ax.plot(snr, ide, "-o", color=IDEAL, lw=2, ms=6, mec=SURFACE, mew=1.5,
                label="DFE, ideal decisions")  # fmt: skip
        ax.errorbar(snr, ber, yerr=[ber - lo, hi - ber], fmt="-o", color=REAL, lw=2, ms=6,
                    mec=SURFACE, mew=1.5, capsize=3,
                    label="DFE, real decisions (95% CI)")  # fmt: skip
        ax.plot(snr, ub, "v", color=REAL, ms=8, mfc="none", mew=1.5,
                label="Upper bound (< 100 errors)")  # fmt: skip
        ax.plot(snr, ide_ub, "v", color=IDEAL, ms=8, mfc="none", mew=1.5)
        ax.set_yscale("log")
        ax.set_ylim(1e-7, 0.3)
        ax.set_title(f"{title}   (DFE tap b/h0 = {b:.2f} at 14 dB)", color=INK, fontsize=11,
                     loc="left")  # fmt: skip
        ax.set_xlabel("SNR at ADC input, E[s²]/σ² (dB)", color=MUTED)
        for s in ("top", "right"):
            ax.spines[s].set_visible(False)
        for s in ("left", "bottom"):
            ax.spines[s].set_color(MUTED)
        ax.tick_params(colors=MUTED)
        ax.grid(color=GRID, lw=0.6, which="major")
    axes[0].set_ylabel("Pre-FEC bit error rate", color=MUTED)
    axes[1].legend(frameon=False, fontsize=9, labelcolor=INK, loc="lower left")
    fig.suptitle(
        "Float model: PAM4 106.25 GBd, MMSE FFE 16 taps + 1-tap DFE, 99.9%-energy channel",
        color=INK, fontsize=12, x=0.01, ha="left",
    )  # fmt: skip
    fig.tight_layout()
    fig.savefig(OUT, dpi=150, facecolor=SURFACE)
    print(OUT)


if __name__ == "__main__":
    main()
