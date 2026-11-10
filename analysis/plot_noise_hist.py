"""Hardware noise histogram vs. the exact model pmf and the Gaussian, to ±7 sigma (Phase B media).

Reads noise_hist_pooled.csv and noise_hist_stats.csv (`make noise-stats`). Run by `make plots`.
Display bins are 5 output units (~0.1 sigma) wide so the 7 sigma tail holds counts; the tests
in noise_hist_stats.csv use the unbinned histogram.
"""

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
HW = "#2a78d6"  # categorical slot 1 (same as plot_ber.py)
RES = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "data" / "results"  # tests only
OUT = (Path(sys.argv[2]) if len(sys.argv) > 2
       else ROOT / "docs" / "media" / "2026-11-11_phase-b_noise-histogram.png")  # fmt: skip
SIGMA = 1581 / 32  # sigma_reg / 2^5, pre-ADC units (checked against the stats sidecar)
W = 5  # display bin width, output units
T_MAX = 7.5
Z_LIM = 5.0  # residual axis; beyond it, triangles at the edge


def main() -> None:
    src, st = RES / "noise_hist_pooled.csv", RES / "noise_hist_stats.csv"
    if not src.exists() or not st.exists():
        sys.exit(f"missing {src.name} / {st.name}; run `make noise-stats` first")
    if f"sigma = {SIGMA} " not in (RES / "noise_hist_pooled.md").read_text():
        sys.exit("sigma in the sidecar does not match this plot's SIGMA")
    rows = list(csv.DictReader(src.open()))
    n = np.array([int(r["n"]) for r in rows])
    cols = {k: np.array([float(r[k]) for r in rows]) for k in
            ("count", "expected_model", "expected_gauss")}  # fmt: skip
    centre = np.arange(-int(T_MAX * SIGMA) // W, int(T_MAX * SIGMA) // W + 1) * W
    idx = np.round(n / W).astype(int) - centre[0] // W  # bin of n: |n - centre| <= W // 2
    ok = (idx >= 0) & (idx < len(centre))
    b = {k: np.bincount(idx[ok], v[ok], minlength=len(centre)) for k, v in cols.items()}
    x = centre / SIGMA
    total = int(cols["count"].sum())

    stats = {(r["lane"], r["test"]): r for r in csv.DictReader(st.open())}
    lanes_ok = sum(int(r["pass"]) for (ln, _), r in stats.items() if ln != "pooled")

    fig, (ax, rx) = plt.subplots(2, 1, figsize=(10, 6.4), sharex=True, facecolor=SURFACE,
                                 gridspec_kw={"height_ratios": [3, 1.2]})  # fmt: skip
    for a in (ax, rx):
        a.set_facecolor(SURFACE)
        for s in ("top", "right"):
            a.spines[s].set_visible(False)
        for s in ("left", "bottom"):
            a.spines[s].set_color(MUTED)
        a.tick_params(colors=MUTED)
        a.grid(color=GRID, lw=0.6)
    for t in (-7, 7):
        for a in (ax, rx):
            a.axvline(t, color=MUTED, lw=0.8, ls=":")
    ax.plot(x, b["expected_gauss"], "--", color=MUTED, lw=1.5, label="Exact Gaussian (rounded)")
    ax.plot(x, b["expected_model"], "-", color=INK, lw=1.0, label="Bit-exact model, exact pmf")
    y = np.where(b["count"] > 0, b["count"], np.nan)  # log axis: empty bins not drawn
    ax.plot(x, y, "o", color=HW, ms=4, mew=0, label="Hardware (8 lanes)")
    ax.set_yscale("log")
    ax.set_ylim(0.3, None)
    ax.set_ylabel(f"Samples per {W}-unit bin (~{W / SIGMA:.2f} σ)", color=MUTED)
    ax.legend(frameon=False, fontsize=9, labelcolor=INK, loc="upper right")
    p = stats[("pooled", "chi2_vs_model_all")]
    g = stats[("pooled", "chi2_vs_gauss_ge4sigma")]
    s = stats[("pooled", "symmetry")]
    ax.text(0.01, 0.97,
            f"χ² vs model, all bins: {float(p['stat']):.0f} on {p['dof']} dof, p = {p['p_value']}\n"
            f"χ² vs Gaussian, |n| ≥ 4σ: {float(g['stat']):.0f} on {g['dof']} dof, "
            f"p = {g['p_value']}\n"
            f"± symmetry: p = {s['p_value']}\nper-lane tests passing: {lanes_ok} of 24",
            transform=ax.transAxes, va="top", fontsize=8.5, color=INK)  # fmt: skip

    e = b["expected_model"]
    z = np.where(e > 0, (b["count"] - e) / np.sqrt(np.maximum(e, 1e-300)), np.nan)
    rx.axhspan(-2, 2, color=GRID, lw=0)
    zc = np.clip(z, -Z_LIM, Z_LIM)
    out = np.abs(z) > Z_LIM  # off-scale residuals pinned to the edge, never dropped
    rx.plot(x[~out], zc[~out], "o", color=HW, ms=3, mew=0)
    rx.plot(x[out & (z > 0)], zc[out & (z > 0)], "^", color=HW, ms=6, mew=0)
    rx.plot(x[out & (z < 0)], zc[out & (z < 0)], "v", color=HW, ms=6, mew=0)
    rx.axhline(0, color=INK, lw=0.8)
    rx.set_ylim(-Z_LIM - 0.6, Z_LIM + 0.6)
    rx.set_yticks([-4, -2, 0, 2, 4])
    rx.set_ylabel("(hw − model) / √model", color=MUTED)
    rx.set_xlabel("Noise sample n / σ", color=MUTED)
    rx.set_xlim(-T_MAX, T_MAX)
    fig.suptitle(f"Hardware Gaussian noise generator: {total:.2e} samples vs. model and Gaussian",
                 color=INK, fontsize=12, x=0.01, ha="left")  # fmt: skip
    fig.tight_layout()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT, dpi=150, facecolor=SURFACE)
    print(OUT)


if __name__ == "__main__":
    main()
