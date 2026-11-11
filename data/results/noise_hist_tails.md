# noise_hist_tails.csv

- Written: 2026-11-11T00:28:09
- Command: `make noise-stats`
- Host commit: b2690934
- numpy 2.5.4, Python 3.14.4
- Source: noise_hist_hw.csv (written 2026-11-10T15:29:54, bitstream 82d89d09, seed 1592590341, 900000678923 (run length 5000000000000) words/lane, elapsed 2.00 h)
- sigma_reg 1581 -> sigma = 49.40625 pre-ADC units
- Pooled over 8 lanes; observed = count of |n| >= abs_n_ge

Interpretation: Counts of samples at or beyond t sigma (after rounding to the integer output). ci95 is the exact Poisson interval on the observed count; both expectations should lie inside it for a correct generator.
