# noise_hist_stats.csv

- Written: 2026-11-11T00:28:09
- Command: `make noise-stats`
- Host commit: b2690934
- numpy 2.5.4, Python 3.14.4
- Source: noise_hist_hw.csv (written 2026-11-10T15:29:54, bitstream 82d89d09, seed 1592590341, 900000678923 (run length 5000000000000) words/lane, elapsed 2.00 h)
- sigma_reg 1581 -> sigma = 49.40625 pre-ADC units
- ALPHA = 0.001 per test; 27 tests; failing: 0

Interpretation: Pass = p >= ALPHA. chi2_vs_model_all compares the hardware |n| histogram to the exact pmf of the bit-exact model (the board is bin-for-bin equal to the model on short runs, noise_hist_exact.csv, so this tests the generator's design on 4e13 samples). chi2_vs_gauss_ge4sigma tests the tail against an exact Gaussian rounded the same way; below 4 sigma the generator's known ~1e-6 sigma approximation is resolvable at this sample count (ADR 0005). symmetry: +n vs -n counts.
