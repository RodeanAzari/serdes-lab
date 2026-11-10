# noise_hist_exact_seed7340033.csv

- Written: 2026-11-10T13:22:03
- Command: `scripts/noise_hist_run.py exact --seed 7340033`
- Host commit: 82d89d09
- Bitstream build id: 82d89d09
- sigma_reg: 1581
- Words per lane: 4194304 (run length 4194304)
- seed (lane_seeds): 7340033
- bins differing: 0
- verdict: PASS
- Columns: lane, n (bin = clamp(n, -512, 511)), counts

Interpretation: ADR 0009 exactness check: the board's histograms vs np.bincount of the bit-exact model noise for the same seeds and word count; PASS means every bin is equal, so the long run's histogram is the model's distribution sampled by the hardware.
