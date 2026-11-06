"""Sampling-phase sweep: post-EQ SNR of the reference RX at all 32 phases per channel.

Decision rule (user, 2026-11-05): keep max-main-cursor sampling if it is within 0.5 dB of the
best phase on both channels at both noise levels. Output: data/results/phase_sweep.csv.
CTLE/TX FIR are held at the values chosen for max-cursor sampling (ADR 0001).
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from model.channel import OVERSAMPLE, apply_tx_fir  # noqa: E402
from model.equalizer import mmse_ffe_dfe  # noqa: E402
from model.link import noise_sigma  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OPERATING_SNR = {"kr_ch2_19p3db": 19.0, "kr_ch4_31p4db": 23.0}  # ~1e-4 BER in the waterfall


def main() -> None:
    rows = []
    for cid, op_snr in OPERATING_SNR.items():
        d = np.load(ROOT / "data" / "channels" / f"{cid}.npz")
        pos, taps = d["pulse_os"], d["tx_taps"]
        peak = int(np.argmax(pos))
        for ph in range(OVERSAMPLE):
            idx = np.arange(ph, len(pos), OVERSAMPLE)
            cur = int(np.argmin(np.abs(idx - peak)))  # sample within half a UI of the peak
            p, c = apply_tx_fir(pos[idx], cur, taps, 1)
            ref = mmse_ffe_dfe(p, c, 16, 3, 1, float(d["noise_var_ref"]))
            op = mmse_ffe_dfe(p, c, 16, 3, 1, noise_sigma(p, op_snr) ** 2)
            rows.append({
                "channel": cid, "phase": ph, "offset_ui": round((idx[cur] - peak) / OVERSAMPLE, 4),
                "h_m1": p[c - 1], "h0": p[c], "h_p1": p[c + 1],
                "snr_ref_noise_db": round(ref.snr_db, 3),
                "operating_input_snr_db": op_snr, "snr_operating_db": round(op.snr_db, 3),
            })  # fmt: skip
    with (ROOT / "data" / "results" / "phase_sweep.csv").open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    for cid in OPERATING_SNR:
        r = [x for x in rows if x["channel"] == cid]
        maxc = max(r, key=lambda x: x["h0"])
        mm = min(r, key=lambda x: abs(x["h_m1"] - x["h_p1"]))
        print(cid)
        for key in ("snr_ref_noise_db", "snr_operating_db"):
            best = max(r, key=lambda x: x[key])
            print(f"  {key:18s} best {best[key]:6.2f} @ph{best['phase']:2d} | "
                  f"max-cursor {maxc[key]:6.2f} @ph{maxc['phase']:2d} "
                  f"(gap {best[key] - maxc[key]:.2f}) | "
                  f"MM {mm[key]:6.2f} @ph{mm['phase']:2d} (gap {best[key]-mm[key]:.2f})")


if __name__ == "__main__":
    main()
