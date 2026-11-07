"""Noise generator sizing sweep (ADR 0005): segment count, x bits, output bits.

Every metric is exact (enumerated over all 2^63 magnitude inputs via model.noise.pmf_g), not
sampled. Metrics per config:
- max_err_sigma: worst |g - g_ideal| at a group centre
- tail_err_g / tail_err_n*: worst |P_gen(|X| >= k) / P_ideal - 1| for levels up to 8 sigma, at the
  generator output (g) and after scaling to pre-ADC units at the operating-point sigmas; the
  ideal is an exact Gaussian rounded the same way. Target (ADR 0003): <= 1%.
- lam_n*: expected chi-square noncentrality of a 4e13-sample histogram of |n| (one bin per
  pre-ADC unit, tail merged to >= 5 expected) against the rounded Gaussian. lam >> dof means
  that histogram would reject an ideal-Gaussian hypothesis even with bug-free RTL.
- lam_n3s/lam_n4s: the same, with every |n| below 3 / 4 sigma merged into one bin (tail-only)
- widths: signed bits of c0, c1, c2 and the Horner intermediate t
"""

from __future__ import annotations

import csv
import itertools
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from model import noise as nz  # noqa: E402

OUT = ROOT / "data/results/noise_sweep.csv"
N_HIST = 4e13  # ADR 0003 overnight hardware histogram
# Operating-point sigma in pre-ADC units: 1344 / 10^(SNR/20), SNRs from fixed_point_sweep.csv
SIGMAS = {"ch4_1e-12": 49.4, "ch2_1e-12": 76.4, "ch4_2p4e-4": 102.0, "ch2_2p4e-4": 157.0}


def main() -> None:
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True,
                            text=True, cwd=ROOT).stdout.strip()  # fmt: skip
    rows = []
    for s, xb, fg in itertools.product((2, 3, 4, 5), (12, 17), (18, 20)):
        cfg = nz.NoiseCfg(sub_bits=s, x_bits=xb, g_frac=fg)
        tb = nz.build_tables(cfg)
        cg = nz.pmf_g(tb)
        assert int(cg.sum()) == 1 << 63
        row: dict[str, object] = {"sub_bits": s, "x_bits": xb, "g_frac": fg, "guard": cfg.guard,
                                  "n_seg": len(tb.c0), **nz.fit_stats(tb)}  # fmt: skip
        row["tail_err_g"] = nz.tail_ratio_err(cg, 2.0**-fg, 8.0)[0]
        row["g_max_sigma"] = (len(cg) - 1) / 2.0**fg
        for name, sig in SIGMAS.items():
            sr = round(sig * (1 << cfg.sigma_frac))
            cn = nz.pmf_n(cg, sr, cfg)
            se = sr / (1 << cfg.sigma_frac)
            row[f"tail_err_n_{name}"] = nz.tail_ratio_err(cn, 1.0 / se, 8.0)[0]
            lam, dof = nz.chi2_noncentrality(cn, se, N_HIST)
            row[f"lam_n_{name}"], row[f"dof_n_{name}"] = lam, dof
            for t_lo in (3, 4):
                lam, dof = nz.chi2_noncentrality(cn, se, N_HIST, float(t_lo))
                row[f"lam_n{t_lo}s_{name}"], row[f"dof_n{t_lo}s_{name}"] = lam, dof
        row["commit"] = commit
        rows.append(row)
        print({k: (f"{v:.3g}" if isinstance(v, float) else v) for k, v in row.items()}, flush=True)
    with OUT.open("w", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=list(rows[0]))
        wr.writeheader()
        wr.writerows(rows)


if __name__ == "__main__":
    main()
