# noise_hist_hw.csv

- Written: 2026-11-10T15:29:54
- Command: `scripts/noise_hist_run.py run`
- Host commit: c0e0cf63
- Bitstream build id: 82d89d09
- sigma_reg: 1581
- Words per lane: 900000678923 (run length 5000000000000)
- seed (lane_seeds): 1592590341
- elapsed_h: 2.00
- Columns: lane, n (bin = clamp(n, -512, 511)), counts

Interpretation: last checkpoint of the long hardware run (ADR 0009). The run stopped here
(host lost the USB NIC at 19:57 on 2026-11-10; no later checkpoint); accepted as the final
data by the user on 2026-11-11 (ADR 0003 outcome note); bins sum to 8 x words. Statistics vs the exact model pmf: model.noise.chi2_gof / symmetry_test.
