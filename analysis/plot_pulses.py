"""Pulse-response plot per channel (Phase A media). Run by `make plots` only."""

from __future__ import annotations

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
INK, MUTED, GRID, SURFACE = "#0b0b0b", "#52514e", "#e4e3df", "#fcfcfb"
SERIES = "#2a78d6"
OUT = ROOT / "docs" / "media" / "2026-11-05_phase-a_pulse-responses.png"
TITLES = {
    "kr_ch2_19p3db": "Moderate: KR Ch2, 19.3 dB IL @ 53.125 GHz",
    "kr_ch4_31p4db": "Hard: KR Ch4, 31.4 dB IL @ 53.125 GHz",
}


def main() -> None:
    files = [ROOT / "data" / "channels" / f"{c}.npz" for c in TITLES]
    missing = [str(f) for f in files if not f.exists()]
    if missing:
        sys.exit(f"missing {missing}; run `make channels` first")
    fig, axes = plt.subplots(1, 2, figsize=(11, 4), sharey=True, facecolor=SURFACE)
    for ax, f, title in zip(axes, files, TITLES.values(), strict=True):
        d = np.load(f)
        pulse, cur = d["pulse"] * 1e3, int(d["cursor"])
        n_pre, n_post = int(d["n_pre"]), int(d["n_post"])
        os_ = d["pulse_os"] * 1e3
        osr = len(os_) / len(pulse)
        t_os = (np.arange(len(os_)) - int(np.argmax(os_))) / osr
        ui = np.arange(len(pulse)) - cur
        ax.set_facecolor(SURFACE)
        ax.axvspan(-n_pre - 0.5, n_post + 0.5, color=GRID, lw=0)
        ax.axhline(0, color=MUTED, lw=0.8)
        ax.plot(t_os, os_, color=SERIES, lw=2)
        ax.plot(ui, pulse, "o", ms=5, color=SERIES, mec=SURFACE, mew=1.5)
        ax.set_xlim(-8, 30)
        ax.set_title(title, color=INK, fontsize=11, loc="left")
        ax.set_xlabel("Time relative to main cursor (UI, 9.41 ps)", color=MUTED)
        ax.annotate(
            f"99.9% energy: {n_pre} pre + {n_post} post",
            xy=(n_post + 0.5, pulse[cur] * 0.9), xytext=(n_post + 2, pulse[cur] * 0.9),
            color=MUTED, fontsize=9, va="center",
        )  # fmt: skip
        ax.annotate(
            f"main cursor {pulse[cur]:.1f} mV", xy=(0, pulse[cur]), xytext=(4, pulse[cur] * 1.02),
            color=INK, fontsize=9, va="center",
        )  # fmt: skip
        for s in ("top", "right"):
            ax.spines[s].set_visible(False)
        for s in ("left", "bottom"):
            ax.spines[s].set_color(MUTED)
        ax.tick_params(colors=MUTED)
        ax.grid(axis="y", color=GRID, lw=0.6)
    axes[0].set_ylabel("Pulse response per unit symbol (mV)", color=MUTED)
    fig.suptitle(
        "802.3dj KR channels after TX FIR + CTLE, 106.25 GBd PAM4 (line: continuous; dots: 1/UI)",
        color=INK, fontsize=12, x=0.01, ha="left",
    )  # fmt: skip
    fig.tight_layout()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT, dpi=150, facecolor=SURFACE)
    print(OUT)


if __name__ == "__main__":
    main()
