"""ILA capture of the FFE output on the board: the slicer's view (Phase C media).

Reads ffe_capture_<name>.csv (`scripts/ber_run.py capture`): 16384 consecutive FFE outputs z
captured by the ILA (equal to the bit-exact model sample for sample, see the sidecar), and the
slicer input v = z - b * level(d[k-1]). Left: v per symbol with the slicer thresholds -t2, 0,
+t2. Right: histograms of v and of z (before the DFE feedback). Run by `make plots`.
"""

from __future__ import annotations

import csv
import re
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
INK, MUTED, GRID, SURFACE = "#0b0b0b", "#52514e", "#e4e3df", "#fcfcfb"
HW = "#2a78d6"  # categorical slot 1 (same as the other plots)
RES = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "data" / "results"
OUT = (Path(sys.argv[2]) if len(sys.argv) > 2
       else ROOT / "docs" / "media" / "2026-11-11_phase-c_ila-ffe-eye.png")  # fmt: skip
NAME = "kr_ch4_31p4db_24db"


def main() -> None:
    src = RES / f"ffe_capture_{NAME}.csv"
    if not src.exists():
        sys.exit(f"missing {src.name}; run scripts/ber_run.py capture first")
    meta = (RES / f"ffe_capture_{NAME}.md").read_text()
    if "verdict: PASS" not in meta:
        sys.exit("capture sidecar does not say PASS (hardware z == model z)")
    t2 = int(re.search(r"- t2: (\d+)", meta).group(1))  # type: ignore[union-attr]
    rows = list(csv.DictReader(src.open()))
    k = np.array([int(r["k"]) for r in rows])
    z = np.array([int(r["z_hw"]) for r in rows])
    v = np.array([int(r["v"]) for r in rows])

    fig, (ax, hx) = plt.subplots(1, 2, figsize=(11, 4.6), facecolor=SURFACE, sharey=True,
                                 gridspec_kw={"width_ratios": [3, 1.2]})  # fmt: skip
    for a in (ax, hx):
        a.set_facecolor(SURFACE)
        for s in ("top", "right"):
            a.spines[s].set_visible(False)
        for s in ("left", "bottom"):
            a.spines[s].set_color(MUTED)
        a.tick_params(colors=MUTED)
        a.grid(color=GRID, lw=0.6)
        for th in (-t2, 0, t2):
            a.axhline(th, color=MUTED, lw=0.9, ls="--")
    ax.plot(k, v, ".", color=HW, ms=1.2, alpha=0.5, mew=0)
    ax.set_xlabel("RX symbol (from the first valid FFE word)", color=MUTED)
    ax.set_ylabel("Slicer input v = z − b·level(d[k−1]), z units", color=MUTED)
    ax.set_title(f"ILA on the Arty: {len(v)} consecutive FFE outputs, Ch4 at 24 dB SNR",
                 color=INK, fontsize=10)  # fmt: skip
    bins = np.arange(min(z.min(), v.min()) - 0.5, max(z.max(), v.max()) + 1.5, 4)
    hx.hist(z, bins=bins, orientation="horizontal", histtype="step", color=MUTED, lw=1,
            label="z (FFE only)")  # fmt: skip
    hx.hist(v, bins=bins, orientation="horizontal", color=HW, alpha=0.7, label="v (after DFE)")
    hx.set_xscale("log")
    hx.set_xlabel("Symbols per bin", color=MUTED)
    hx.legend(frameon=False, fontsize=8, labelcolor=INK, loc="upper right")
    fig.text(0.01, 0.01, "Dashed: slicer thresholds −t2, 0, +t2. Every captured sample equals "
             "the bit-exact model's z for the same seeds.", color=MUTED, fontsize=8)  # fmt: skip
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT, dpi=150)
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
