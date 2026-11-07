"""`make model-kp4`: float model, KP4 statistics per channel / SNR / DFE mode / precoder.

Measured vs. independent-error prediction (buildplan §7.2): errors per codeword (0..16+),
post-FEC CER (> 15 RS-symbol errors), burst lengths. Real vs. ideal DFE decisions and precoder
off/on share payload and noise draws (paired). Non-interleaved and 2-way interleaved rows group
the same lane errors (paired). Output: data/results/kp4_model.csv (sidecar kp4_model.md).
"""

from __future__ import annotations

import csv
import itertools
import subprocess
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from model import fec_stats as fs  # noqa: E402
from model import rs  # noqa: E402
from model.equalizer import mmse_ffe_dfe  # noqa: E402
from model.kp4link import run_kp4  # noqa: E402
from model.link import noise_sigma  # noqa: E402
from model.stats import MIN_ERRORS_FOR_VALUE, clopper_pearson, upper_bound  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SNR_DB = {"kr_ch2_19p3db": (16.5, 17.0, 17.5, 18.0), "kr_ch4_31p4db": (20.5, 21.0, 21.5, 22.0)}
REF_TAPS, REF_PRE = 16, 3  # same reference equalizer as model_ber_float.csv
N_CW, CHUNK_CW = 10_000, 1_000
SEED_DATA, SEED_NOISE = 20261107, 707


def main() -> None:
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True,
                            text=True, cwd=ROOT).stdout.strip()  # fmt: skip
    rows = []
    for cid, snrs in SNR_DB.items():
        d = np.load(ROOT / "data" / "channels" / f"{cid}.npz")
        cur, n_pre, n_post = int(d["cursor"]), int(d["n_pre"]), int(d["n_post"])
        pulse = d["pulse"][cur - n_pre : cur + n_post + 1]
        for snr, ideal, prec in itertools.product(snrs, (False, True), (False, True)):
            sig = noise_sigma(pulse, snr)
            eq = mmse_ffe_dfe(pulse, n_pre, REF_TAPS, REF_PRE, 1, sig**2)
            rs_err, bursts = [], []
            bits = bit_errs = checked = mism = 0
            for k in range(N_CW // CHUNK_CW):
                r = run_kp4(pulse, n_pre, eq.taps, REF_PRE, float(eq.dfe[0]), eq.h0, sig,
                            CHUNK_CW, SEED_DATA + k, SEED_NOISE + k, ideal, prec)  # fmt: skip
                rs_err.append(r.rs_err)
                bursts.append(fs.burst_lengths(r.pam4_err))
                bits += r.bits
                bit_errs += r.bit_errors
                checked += r.decode_checked
                mism += r.decode_mismatches
            if mism:
                sys.exit(f"decoder contradicts the bounded-distance rule at {cid} {snr} dB")
            lane, bl = np.concatenate(rs_err), np.concatenate(bursts)
            p_sym = float(lane.mean())
            for il in (1, 2):
                n = fs.errors_per_codeword(lane, il)
                hist = fs.error_histogram(n)
                fails = int(np.count_nonzero(n > rs.T))
                lo, hi = clopper_pearson(fails, len(n))
                ok = fails >= MIN_ERRORS_FOR_VALUE
                pred = fs.independent_cer(p_sym)
                row = {
                    "channel": cid, "snr_db": snr, "snr_definition": "E[s^2]/sigma^2 at ADC input",
                    "equalizer": f"MMSE FFE{REF_TAPS}(pre{REF_PRE})+DFE1, float",
                    "dfe_decisions": "ideal" if ideal else "real",
                    "precoder": "on" if prec else "off", "interleave": il,
                    "codewords": len(n), "bits": bits, "bit_errors": bit_errs,
                    "ber": bit_errs / bits, "rs_symbol_error_rate": p_sym,
                    "mean_errors_per_cw": float(n.mean()), "var_errors_per_cw": float(n.var()),
                    "var_binomial": rs.N * p_sym * (1 - p_sym),
                    "cw_errors": fails, "cer": fails / len(n) if ok else "",
                    "cer_ci95_lo": lo if ok else "", "cer_ci95_hi": hi if ok else "",
                    "cer_upper_bound95": "" if ok else upper_bound(fails, len(n)),
                    "cer_pred_independent": pred,
                    "cer_over_pred": fails / len(n) / pred if ok and pred > 0 else "",
                    **{f"h{i}": int(v) for i, v in enumerate(hist)},
                    **{f"h{i}_pred": float(v) for i, v in
                       enumerate(fs.independent_histogram(p_sym, len(n)))},
                    "bursts": len(bl), "burst_mean": float(bl.mean()) if len(bl) else 0.0,
                    "burst_max": int(bl.max()) if len(bl) else 0,
                    "bursts_ge4": int(np.count_nonzero(bl >= 4)),
                    "decode_checked": checked, "seed_data": SEED_DATA, "seed_noise": SEED_NOISE,
                    "commit": commit,
                }  # fmt: skip
                rows.append(row)
                shown = f"{fails / len(n):.2e}" if ok else f"<{upper_bound(fails, len(n)):.1e}"
                print(f"{cid} {snr} dB dfe={'ideal' if ideal else 'real'} prec={int(prec)} "
                      f"il={il}: p_sym {p_sym:.2e} CER {shown} ({fails}) pred {pred:.2e}",
                      flush=True)  # fmt: skip
    out = ROOT / "data" / "results" / "kp4_model.csv"
    with out.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


if __name__ == "__main__":
    main()
