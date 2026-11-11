"""Hardware pre-FEC BER vs. the bit-exact fixed-point model, Ch4 and Ch2 (Phase C media).

Reads ber_hw_<channel>[_pre].csv (board, `scripts/ber_run.py sweep`) and
ber_model_<channel>[_pre].csv (`scripts/ber_run.py model`). Run by `make plots`.
Bars: model 95% batch-means CI over >= 20 independent runs (errors are bursty: DFE error
propagation, precoder pairs); board 95% Clopper-Pearson (10^10 bits: narrower than the
markers except at the lowest-BER points, where it is optimistic by the burst factor).
A board point with no model row needed more model bits than the cap
(the software model is ~10^4 x slower than the board); it is drawn without a model partner.
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
HW = "#2a78d6"  # categorical slot 1 (same as plot_ber.py / plot_noise_hist.py)
RES = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "data" / "results"
OUT = (Path(sys.argv[2]) if len(sys.argv) > 2
       else ROOT / "docs" / "media" / "2026-11-11_phase-c_ber-hw-vs-model.png")  # fmt: skip
SETS = [("kr_ch4_31p4db", "Ch4 (31.4 dB loss), precoder off"),
        ("kr_ch2_19p3db_pre", "Ch2 (19.3 dB loss), precoder on")]  # fmt: skip


def load(path: Path, batch: bool) -> dict[str, np.ndarray]:
    """batch: use the batch-means CI (model; valid with bursty errors) as ci95_lo/hi."""
    rows = list(csv.DictReader(path.open()))
    sfx = "_batch" if batch else ""
    d = {k: np.array([float(r[k]) for r in rows]) for k in ("snr_db", "bits", "bit_errors", "ber")}
    d["ci95_lo"] = np.array([float(r["ci95_lo" + sfx]) for r in rows])
    d["ci95_hi"] = np.array([float(r["ci95_hi" + sfx]) for r in rows])
    return d


def main() -> None:
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.6), facecolor=SURFACE, sharey=True)
    for ax, (name, title) in zip(axes, SETS, strict=True):
        hw_p, mo_p = RES / f"ber_hw_{name}.csv", RES / f"ber_model_{name}.csv"
        if not hw_p.exists() or not mo_p.exists():
            sys.exit(f"missing {hw_p.name} / {mo_p.name}; run scripts/ber_run.py sweep / model")
        hw, mo = load(hw_p, False), load(mo_p, True)
        ax.set_facecolor(SURFACE)
        for s in ("top", "right"):
            ax.spines[s].set_visible(False)
        for s in ("left", "bottom"):
            ax.spines[s].set_color(MUTED)
        ax.tick_params(colors=MUTED)
        ax.grid(color=GRID, lw=0.6, which="both")
        series = ((mo, INK, "s", "Bit-exact model (software, batch CI)", -0.06),
                  (hw, HW, "o", "Hardware (Arty A7, 1 Gb/s)", 0.06))
        for d, color, mk, lab, dx in series:
            err = np.vstack([d["ber"] - d["ci95_lo"], d["ci95_hi"] - d["ber"]])
            ax.errorbar(d["snr_db"] + dx, d["ber"], yerr=err, fmt=mk, color=color, ms=5,
                        mfc=color if mk == "o" else "none", capsize=3, lw=1, label=lab)  # fmt: skip
        ax.plot(hw["snr_db"], hw["ber"], "-", color=HW, lw=0.8, alpha=0.6)
        for x, y, b, e in zip(hw["snr_db"], hw["ber"], hw["bits"], hw["bit_errors"], strict=True):
            ax.annotate(f"{int(e)} err\n{b:.0e} b", (x, y), textcoords="offset points",
                        xytext=(6, 4), fontsize=7, color=MUTED)  # fmt: skip
        ax.set_yscale("log")
        ax.set_title(title, color=INK, fontsize=10)
        ax.set_xlabel("SNR at the ADC input, dB (PAM4 Es · Σh² / σ²)", color=MUTED)
        ax.legend(frameon=False, fontsize=8, labelcolor=INK, loc="lower left")
    axes[0].set_ylabel("Pre-FEC BER (95% CI)", color=MUTED)
    fig.suptitle("Phase C: board BER vs bit-exact model, MMSE FFE 16 + 1-tap DFE, fixed taps",
                 color=INK, fontsize=11)  # fmt: skip
    fig.tight_layout()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT, dpi=150)
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
