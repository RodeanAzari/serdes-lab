"""Model vs. serdespy BER overlay (Phase A media). Run by `make plots` only."""

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
MODEL, SDP = "#2a78d6", "#eb6834"  # categorical slots 1, 2 (same as plot_ber.py)
SRC = ROOT / "data" / "results" / "serdespy_ber.csv"
OUT = ROOT / "docs" / "media" / "2026-11-07_phase-a_serdespy-overlay.png"
TITLES = {"kr_ch2_19p3db": "KR Ch2, 19.3 dB IL", "kr_ch4_31p4db": "KR Ch4, 31.4 dB IL"}


def main() -> None:
    if not SRC.exists():
        sys.exit(f"missing {SRC}; run `make xcheck` first")
    rows = list(csv.DictReader(SRC.open()))
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.4), sharey=True, facecolor=SURFACE)
    for ax, (cid, title) in zip(axes, TITLES.items(), strict=True):
        r = [x for x in rows if x["channel"] == cid]

        def col(k: str, r: list[dict[str, str]] = r) -> np.ndarray:
            return np.array([float(x[k]) for x in r])

        snr = col("snr_db")
        z_max = float(np.max(np.abs(col("z"))))
        ax.set_facecolor(SURFACE)
        for side, color, marker, mfc, label in (
            ("model", MODEL, "o", MODEL, "This project's model"),
            ("serdespy", SDP, "s", SURFACE, "serdespy 1.0 (independent engine)"),
        ):
            ber, se = col(f"{side}_ber"), col(f"{side}_ber_se")
            ax.errorbar(snr, ber, yerr=1.96 * se, fmt="-" + marker, color=color, mfc=mfc,
                        lw=2, ms=8, mew=2, capsize=3, label=label)  # fmt: skip
        ax.set_yscale("log")
        ax.set_ylim(1e-6, 3e-3)
        ax.set_title(f"{title}   (max |z| = {z_max:.2f})", color=INK, fontsize=11, loc="left")
        ax.set_xlabel("SNR at ADC input, E[s²]/σ² (dB)", color=MUTED)
        for s in ("top", "right"):
            ax.spines[s].set_visible(False)
        for s in ("left", "bottom"):
            ax.spines[s].set_color(MUTED)
        ax.tick_params(colors=MUTED)
        ax.grid(color=GRID, lw=0.6, which="major")
    axes[0].set_ylabel("Pre-FEC bit error rate (95% CI, batch means)", color=MUTED)
    axes[1].legend(frameon=False, fontsize=9, labelcolor=INK, loc="upper right")
    fig.suptitle(
        "Cross-check: same pulse, taps and σ; separate generators, FFE, DFE, slicer and demap",
        color=INK, fontsize=12, x=0.01, ha="left",
    )  # fmt: skip
    fig.tight_layout()
    fig.savefig(OUT, dpi=150, facecolor=SURFACE)
    print(OUT)


if __name__ == "__main__":
    main()
