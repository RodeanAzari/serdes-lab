# noise_hist_exact_3a1f17ee_fail.csv

- Written: 2026-11-10T12:24:04
- Command: `scripts/noise_hist_run.py exact`
- Host commit: dad02440
- Bitstream build id: 3a1f17ee
- sigma_reg: 1581
- Words per lane: 4194304 (run length 4194304)
- seed (lane_seeds): 1592590341
- bins differing: 4
- verdict: FAIL
- Columns: lane, n (bin = clamp(n, -512, 511)), counts

Interpretation: FAIL is real and diagnosed. Each lane can lose only its last sample (lanes 2, 4, 5, 7 here). Repeated READs of the same histogram flip that one bin between old and new, so the memory was right and the readback was not. Cause: Vivado mapped hist_bram's write port with a constant enable plus an idle write-back, which collided with readout (fixed in 82d89d0; docs/log.md 2026-11-10). Kept as the record of the failure.
