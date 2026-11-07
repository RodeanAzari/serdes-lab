"""Errors per KP4 codeword, measured vs. independent-error prediction (model). `make plots` only."""

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
OFF, ON = "#2a78d6", "#eb6834"  # categorical slots 1, 2 (same as plot_ber.py)
SRC = ROOT / "data" / "results" / "kp4_model.csv"
OUT = ROOT / "docs" / "media" / "2026-11-07_phase-a_kp4-errors-per-codeword.png"
PANELS = {
    ("kr_ch2_19p3db", 17.0): "KR Ch2, 19.3 dB IL",
    ("kr_ch4_31p4db", 21.0): "KR Ch4, 31.4 dB IL",
}
BINS = 17  # 0..15, 16+


def pick(rows: list[dict[str, str]], cid: str, snr: float, prec: str) -> dict[str, str]:
    r = [x for x in rows if x["channel"] == cid and float(x["snr_db"]) == snr
         and x["dfe_decisions"] == "real" and x["precoder"] == prec and x["interleave"] == "1"]
    if len(r) != 1:
        sys.exit(f"expected one row for {cid} {snr} dB precoder {prec}, found {len(r)}")
    return r[0]


def cer_text(r: dict[str, str]) -> str:
    v = f"{float(r['cer']):.2%}" if r["cer"] else f"< {float(r['cer_upper_bound95']):.1e}"
    return f"CER {v} vs {float(r['cer_pred_independent']):.2%} predicted"


def main() -> None:
    if not SRC.exists():
        sys.exit(f"missing {SRC}; run `make model-kp4` first")
    rows = list(csv.DictReader(SRC.open()))
    x = np.arange(BINS)
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.6), sharey=True, facecolor=SURFACE)
    for ax, ((cid, snr), title) in zip(axes, PANELS.items(), strict=True):
        off, on = pick(rows, cid, snr, "off"), pick(rows, cid, snr, "on")
        ax.set_facecolor(SURFACE)
        ax.axvspan(15.5, 16.5, color=GRID, lw=0)  # uncorrectable: > t = 15
        pred = np.array([float(off[f"h{i}_pred"]) for i in range(BINS)])
        ax.plot(x, pred, "--", color=MUTED, lw=1.5,
                label="Independent errors, same symbol error rate (precoder off)")  # fmt: skip
        for r, color, marker, mfc, label in (
            (off, OFF, "o", OFF, "Measured, precoder off"),
            (on, ON, "s", SURFACE, "Measured, precoder on"),
        ):
            h = np.array([float(r[f"h{i}"]) for i in range(BINS)])
            h[h == 0] = np.nan  # log axis: empty bins are not drawn
            ax.plot(x, h, "-" + marker, color=color, mfc=mfc, lw=2, ms=7, mew=2,
                    label=f"{label}: {cer_text(r)}")  # fmt: skip
        ax.set_yscale("log")
        ax.set_xticks(x, [str(i) for i in range(16)] + ["16+"])
        ax.set_title(f"{title} at {snr:g} dB SNR, real DFE decisions", color=INK, fontsize=11,
                     loc="left")  # fmt: skip
        ax.set_xlabel("RS-symbol errors per codeword (shaded: uncorrectable)", color=MUTED)
        for s in ("top", "right"):
            ax.spines[s].set_visible(False)
        for s in ("left", "bottom"):
            ax.spines[s].set_color(MUTED)
        ax.tick_params(colors=MUTED)
        ax.grid(color=GRID, lw=0.6, which="major")
        ax.legend(frameon=False, fontsize=8, labelcolor=INK, loc="lower left")
    axes[0].set_ylabel(f"Codewords (of {int(off['codewords']):,})", color=MUTED)
    fig.suptitle(
        "KP4 RS(544,514) errors per codeword, float model: DFE bursts vs. the independent-error"
        " prediction", color=INK, fontsize=12, x=0.01, ha="left",
    )  # fmt: skip
    fig.tight_layout()
    fig.savefig(OUT, dpi=150, facecolor=SURFACE)
    print(OUT)


if __name__ == "__main__":
    main()
