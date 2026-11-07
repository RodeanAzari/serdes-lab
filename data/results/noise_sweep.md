# noise_sweep.csv

- **Command:** `.venv/bin/python scripts/noise_tables.py`; deterministic, ~8 min
- **Commit:** `fcd611f`
- **Tools:** Python 3.14.4, numpy 2.5.4, scipy 1.18.1 (`ndtri`/`ndtr` as the Gaussian reference)
- **Model:** `model/noise.py` (ADR 0003 method), guard 6 b, σ register 5 fraction bits, noise 16 b
- **Exact, not sampled:** `pmf_g` enumerates all 2⁶³ magnitude inputs by group (integer counts,
  total checked = 2⁶³). No seed involved.
- **σ values (pre-ADC units, 1344 / 10^(SNR/20)):** ch4_1e-12 49.4, ch2_1e-12 76.4,
  ch4_2p4e-4 102, ch2_2p4e-4 157 (SNRs from `fixed_point_sweep.csv`)
- **Columns:** `max_err_sigma` worst |g − ideal| at group centres; `tail_err_*` worst relative tail
  error to 8σ vs. an exact Gaussian rounded the same way (target ≤ 1%); `lam_n_*` expected
  chi-square excess of a 4 × 10¹³-sample |n| histogram vs. the rounded Gaussian (one bin per
  pre-ADC unit, tail merged to ≥ 5 expected), `lam_n3s_*` / `lam_n4s_*` with |n| < 3σ / 4σ merged
  into one bin; `*_bits` signed widths of c0, c1, c2 and the Horner intermediate t

**Interpretation:** every config meets the 1% tail target (worst 2.2e-4 at S = 2). For S ≥ 3 the
tail error is flat at ~5e-5, because the 63-bit input leaves only ~10⁴ distinct values beyond 8σ.
Chosen S = 4, XB = 17, FG = 20 (ADR 0005): tail 4.5e-5, max error 2.4e-6σ. Against the ideal
Gaussian, the full-range λ is ≥ 4e4 for every config (dof 354–1098), so a full-range 4e13 chi-square
would reject bug-free RTL. Tail-only from 4σ, the chosen config gives λ = 3.9 / 157 dof at σ = 49.4
and ≤ 17 / 471 at the other σ values, inside the statistic's spread. From 3σ it fails (λ 128–836).
