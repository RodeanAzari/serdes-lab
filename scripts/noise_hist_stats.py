"""Noise-tail validation statistics for the hardware histogram (ADR 0005 §validation, ADR 0009).

Input: data/results/noise_hist_hw.csv (lane, n, count), written by scripts/noise_hist_run.py.
Tests, per lane and pooled over the 8 lanes (independent lfsr258 seeds):
  1. chi-square of |n| vs the EXACT model pmf (model.noise.pmf_n), all bins merged to >= 5 expected
  2. chi-square of |n| vs the rounded Gaussian, |n| >= 4 sigma only (below that the generator's
     ~1e-6 sigma approximation error is visible at 4e13 samples, ADR 0005)
  3. sign symmetry, +m vs -m
Each test passes at p >= ALPHA, fixed before the long run's data was looked at (ADR 0009).
Also tail counts beyond 4..7 sigma: observed (95% CI) vs model and Gaussian expectations.

Outputs: noise_hist_stats.csv (tests), noise_hist_tails.csv (tail counts),
noise_hist_pooled.csv (signed pooled histogram with model/Gaussian expected counts, read by
analysis/plot_noise_hist.py), each with a sidecar .md.
"""

from __future__ import annotations

import csv
import datetime as dt
import math
import subprocess
import sys
from pathlib import Path

import numpy as np
from scipy.special import ndtr  # type: ignore[import-untyped]
from scipy.stats import chi2 as chi2_dist  # type: ignore[import-untyped]

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from model import noise as nz  # noqa: E402

RES = Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / "data" / "results"  # tests only
SRC = Path(sys.argv[1]) if len(sys.argv) > 1 else RES / "noise_hist_hw.csv"
LANES, NB = 8, 1024
SIGMA_REG = round(49.4 * 32)  # must match scripts/noise_hist_run.py (checked against the sidecar)
ALPHA = 1e-3  # per test; 27 tests -> ~2.7% family-wise false-fail rate for a correct generator
TAIL_T = (4.0, 5.0, 6.0, 7.0)


def load() -> tuple[np.ndarray, dict[str, str]]:
    if not SRC.exists():
        sys.exit(f"missing {SRC}; run `scripts/noise_hist_run.py run` first")
    h = np.zeros((LANES, NB), dtype=np.int64)
    with SRC.open() as fh:
        for r in csv.DictReader(fh):
            h[int(r["lane"]), int(r["n"]) + NB // 2] = int(r["count"])
    meta = {}
    for line in SRC.with_suffix(".md").read_text().splitlines():
        if line.startswith("- ") and ": " in line:
            k, v = line[2:].split(": ", 1)
            meta[k] = v
    if int(meta["sigma_reg"]) != SIGMA_REG:
        sys.exit(f"sidecar sigma_reg {meta['sigma_reg']} != {SIGMA_REG}")
    words = int(meta["Words per lane"].split()[0])
    if not np.all(h.sum(axis=1) == words):
        sys.exit(f"lane sums {h.sum(axis=1)} != words per lane {words}")
    return h, meta


def poisson_ci(k: int, conf: float = 0.95) -> tuple[float, float]:
    """Exact (Garwood) interval for a Poisson mean given k observed."""
    a = 1 - conf
    lo = 0.0 if k == 0 else float(chi2_dist.ppf(a / 2, 2 * k)) / 2
    return lo, float(chi2_dist.ppf(1 - a / 2, 2 * k + 2)) / 2


def tail_ge(abs_counts: np.ndarray, k: int) -> float:
    return float(abs_counts[k:].sum())


def sidecar(path: Path, meta: dict[str, str], extra: list[str], interp: str) -> None:
    commit = subprocess.run(["git", "rev-parse", "--short=8", "HEAD"], capture_output=True,
                            text=True, cwd=ROOT).stdout.strip()  # fmt: skip
    lines = [f"# {path.name}", "", f"- Written: {dt.datetime.now().isoformat(timespec='seconds')}",
             "- Command: `make noise-stats`", f"- Host commit: {commit}",
             f"- numpy {np.__version__}, Python {sys.version.split()[0]}",
             f"- Source: {SRC.name} (written {meta['Written']}, bitstream "
             f"{meta['Bitstream build id']}, seed {meta['seed (lane_seeds)']}, "
             f"{meta['Words per lane']} words/lane, elapsed {meta.get('elapsed_h', '?')} h)",
             f"- sigma_reg {SIGMA_REG} -> sigma = {SIGMA_REG / 32} pre-ADC units",
             *extra, "", f"Interpretation: {interp}"]  # fmt: skip
    path.with_suffix(".md").write_text("\n".join(lines) + "\n")


def main() -> int:
    h, meta = load()
    cfg = nz.NoiseCfg()
    sigma = SIGMA_REG / 2**cfg.sigma_frac
    count_n = nz.pmf_n(nz.pmf_g(nz.build_tables(cfg)), SIGMA_REG, cfg)
    p_model = count_n.astype(np.float64) / 2.0**nz.U_BITS
    if len(p_model) > NB // 2:
        sys.exit("model |n| exceeds the histogram clamp; the fold would be wrong")
    p_gauss = nz.gauss_abs_pmf(sigma, NB // 2)
    lo4 = math.ceil(4 * sigma)

    rows: list[dict[str, object]] = []
    groups = [(str(i), h[i]) for i in range(LANES)] + [("pooled", h.sum(axis=0))]
    for name, hist in groups:
        a = nz.fold_abs(hist)
        for test, (stat, dof, p) in (
            ("chi2_vs_model_all", nz.chi2_gof(a, p_model)),
            ("chi2_vs_gauss_ge4sigma", nz.chi2_gof(a, p_gauss, lo4)),
            ("symmetry", nz.symmetry_test(hist)),
        ):
            rows.append({"lane": name, "samples": int(hist.sum()), "test": test,
                         "stat": f"{stat:.2f}", "dof": dof, "p_value": f"{p:.4g}",
                         "pass": int(p >= ALPHA)})  # fmt: skip
    out = RES / "noise_hist_stats.csv"
    with out.open("w", newline="") as fh:
        wr = csv.DictWriter(fh, fieldnames=list(rows[0]))
        wr.writeheader()
        wr.writerows(rows)
    n_fail = sum(1 for r in rows if not r["pass"])
    sidecar(out, meta, [f"- ALPHA = {ALPHA} per test; {len(rows)} tests; failing: {n_fail}"],
            "Pass = p >= ALPHA. chi2_vs_model_all compares the hardware |n| histogram to the "
            "exact pmf of the bit-exact model (the board is bin-for-bin equal to the model on "
            "short runs, noise_hist_exact.csv, so this tests the generator's design on 4e13 "
            "samples). chi2_vs_gauss_ge4sigma tests the tail against an exact Gaussian rounded "
            "the same way; below 4 sigma the generator's known ~1e-6 sigma approximation is "
            "resolvable at this sample count (ADR 0005). symmetry: +n vs -n counts.")

    pooled = h.sum(axis=0)
    a = nz.fold_abs(pooled)
    total = float(pooled.sum())
    tails = []
    for t in TAIL_T:
        k = math.ceil(t * sigma - 0.5)  # |n| >= k  <=>  rounded value at or beyond t sigma
        obs = int(tail_ge(a, k))
        lo, hi = poisson_ci(obs)
        tails.append({"t_sigma": t, "abs_n_ge": k, "observed": obs,
                      "ci95_lo": f"{lo:.2f}", "ci95_hi": f"{hi:.2f}",
                      "expected_model": f"{total * p_model[k:].sum():.2f}",
                      "expected_gauss": f"{total * 2 * ndtr(-(k - 0.5) / sigma):.2f}"})  # fmt: skip
    out_t = RES / "noise_hist_tails.csv"
    with out_t.open("w", newline="") as fh:
        wr = csv.DictWriter(fh, fieldnames=list(tails[0]))
        wr.writeheader()
        wr.writerows(tails)
    sidecar(out_t, meta, ["- Pooled over 8 lanes; observed = count of |n| >= abs_n_ge"],
            "Counts of samples at or beyond t sigma (after rounding to the integer output). "
            "ci95 is the exact Poisson interval on the observed count; both expectations "
            "should lie inside it for a correct generator.")

    n = np.arange(-NB // 2, NB // 2)
    m = np.minimum(np.abs(n), NB // 2)
    pm = np.zeros(NB // 2 + 1)
    pm[: len(p_model)] = p_model
    half = np.where(n == 0, 1.0, 0.5)  # signed pmf: |n| mass split over +/-n
    out_p = RES / "noise_hist_pooled.csv"
    with out_p.open("w", newline="") as fh:
        wr = csv.writer(fh)
        wr.writerow(["n", "count", "expected_model", "expected_gauss"])
        for i in range(NB):
            wr.writerow([int(n[i]), int(pooled[i]), f"{total * pm[m[i]] * half[i]:.6g}",
                         f"{total * p_gauss[m[i]] * half[i]:.6g}"])  # fmt: skip
    sidecar(out_p, meta, ["- Columns: n (pre-ADC units), count (8 lanes), expected_model "
                          "(exact model pmf), expected_gauss (rounded exact Gaussian)"],
            "Pooled signed histogram for the ±7 sigma plot (analysis/plot_noise_hist.py).")

    for r in rows:
        if r["lane"] == "pooled" or not r["pass"]:
            print(f"{r['lane']:>6} {r['test']:<24} stat {r['stat']:>10} dof {r['dof']:>4} "
                  f"p {r['p_value']:>8} {'PASS' if r['pass'] else 'FAIL'}")
    for t in tails:
        print(f">= {t['t_sigma']} sigma: {t['observed']} [{t['ci95_lo']}, {t['ci95_hi']}]  "
              f"model {t['expected_model']}  gauss {t['expected_gauss']}")
    print(f"{len(rows) - n_fail}/{len(rows)} tests pass (alpha {ALPHA})")
    return 0 if n_fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
