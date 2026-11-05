"""`make model-ber`: floating-point BER waterfall per channel (reference for hardware, Phase A).

Equalizer: MMSE FFE (REF_TAPS, REF_PRE) + 1-tap DFE with real decisions, re-solved per SNR.
Output: data/results/model_ber_float.csv (sidecar: model_ber_float.md).
"""

from __future__ import annotations

import csv
import subprocess
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from model.equalizer import mmse_ffe_dfe  # noqa: E402
from model.link import noise_sigma, run_link  # noqa: E402
from model.stats import (  # noqa: E402
    MIN_ERRORS_FOR_VALUE,
    clopper_pearson,
    pam4_ber_awgn,
    upper_bound,
)

ROOT = Path(__file__).resolve().parents[1]
CHANNELS = ["kr_ch2_19p3db", "kr_ch4_31p4db"]
SNR_DB = np.arange(14.0, 30.5, 1.0)
REF_TAPS, REF_PRE = 16, 3
CHUNK = 2_000_000  # symbols per chunk
MAX_SYM = 50_000_000  # per SNR point
TARGET_ERRORS = 200
SEED_DATA, SEED_NOISE = 20261105, 77
STOP_BER = 1e-7  # skip points whose prediction is far below what MAX_SYM can resolve


def main() -> None:
    commit = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, cwd=ROOT
    ).stdout.strip()
    rows = []
    for cid in CHANNELS:
        d = np.load(ROOT / "data" / "channels" / f"{cid}.npz")
        cur, n_pre, n_post = int(d["cursor"]), int(d["n_pre"]), int(d["n_post"])
        pulse = d["pulse"][cur - n_pre : cur + n_post + 1]  # 99.9%-energy truncation
        for snr in SNR_DB:
            nv = noise_sigma(pulse, snr) ** 2
            eq = mmse_ffe_dfe(pulse, n_pre, REF_TAPS, REF_PRE, 1, nv)
            pred = pam4_ber_awgn(eq.snr_db)
            if pred < STOP_BER:
                break
            bits = errs = syms = serrs = ierrs = 0
            k = 0
            while errs < TARGET_ERRORS and syms < MAX_SYM:
                r = run_link(pulse, n_pre, eq.taps, REF_PRE, float(eq.dfe[0]), eq.h0, snr,
                             CHUNK, SEED_DATA + k, SEED_NOISE + k)  # fmt: skip
                bits += r.bits
                errs += r.bit_errors
                syms += r.symbols
                serrs += r.symbol_errors
                # Same seeds, true previous symbol in the DFE: paired error-propagation baseline.
                ierrs += run_link(pulse, n_pre, eq.taps, REF_PRE, float(eq.dfe[0]), eq.h0, snr,
                                  CHUNK, SEED_DATA + k, SEED_NOISE + k, ideal_dfe=True
                                  ).bit_errors  # fmt: skip
                k += 1
            lo, hi = clopper_pearson(errs, bits)
            is_value = errs >= MIN_ERRORS_FOR_VALUE
            row = {
                "channel": cid, "snr_db": snr, "snr_definition": "E[s^2]/sigma^2 at ADC input",
                "equalizer": f"MMSE FFE{REF_TAPS}(pre{REF_PRE})+DFE1 real decisions, float",
                "channel_taps": f"{n_pre}pre+{n_post}post", "precoder": "off",
                "interleave": "n/a (no FEC)", "seed_data": SEED_DATA, "seed_noise": SEED_NOISE,
                "chunks": k, "bits": bits, "bit_errors": errs,
                "ber": errs / bits if is_value else "",
                "ber_ci95_lo": lo if is_value else "", "ber_ci95_hi": hi if is_value else "",
                "ber_upper_bound95": "" if is_value else upper_bound(errs, bits),
                "symbols": syms, "symbol_errors": serrs,
                "mmse_slicer_snr_db": round(eq.snr_db, 3), "ber_pred_gaussian": pred,
                "dfe_b_over_h0": round(float(eq.dfe[0]) / eq.h0, 4),
                "ideal_dfe_bit_errors": ierrs,
                "ber_ideal_dfe": ierrs / bits if ierrs >= MIN_ERRORS_FOR_VALUE else "",
                "ber_ideal_dfe_upper_bound95": (
                    "" if ierrs >= MIN_ERRORS_FOR_VALUE else upper_bound(ierrs, bits)),
                "commit": commit,
            }  # fmt: skip
            rows.append(row)
            shown = f"{errs / bits:.3e}" if is_value else f"<{upper_bound(errs, bits):.1e}"
            print(f"{cid} SNR {snr:4.1f} dB: BER {shown} ({errs}/{bits}) "
                  f"ideal-DFE errs {ierrs} pred {pred:.3e}")
    out = ROOT / "data" / "results" / "model_ber_float.csv"
    with out.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


if __name__ == "__main__":
    main()
