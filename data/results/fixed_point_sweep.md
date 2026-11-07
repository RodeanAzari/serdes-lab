# fixed_point_sweep.csv

- **Command:** `.venv/bin/python scripts/fixed_point_sweep.py` (writes this and `fixed_point_ber.csv`); seeded, ~2 min
- **Commit:** `72fd78d`
- **Tools:** Python 3.14.4, numpy 2.5.4, scipy 1.18.1
- **Channel/EQ:** `data/channels/kr_ch{2,4}*.npz`, 99.9%-energy truncation, scaled and rounded
  to integer taps (`fixed.channel_int`); MMSE FFE16 (main tap 4, ADR 0002) + DFE1; precoder off
- **SNR:** docs/design.md definition, on the quantized channel. `input_snr_db` = where the
  float receiver's Gaussian-predicted BER is `target_ber` (2.4e-4 or 1e-12)
- **Seeds:** payload 101, noise SeedSequence(202, spawn_key=(1,)); 10⁶ symbols per row
- **Metric:** slicer SNR = 5 / E[e²], e = (z − b·a[k−1]) / h0 − a[k] (ideal-decision DFE),
  float vs. fixed on identical samples; `penalty_db` = float − fixed. Resolution ≈ ±0.02 dB
  (the fixed receiver's rounded slicer scale can beat the MMSE scale slightly: small negatives)
- **Sweeps:** one factor at a time, others at `GEN` (12-bit ADC, clip 4, frac 8, coef 18,
  out 20); `chosen` row = ADR 0004 config

**Interpretation:** the ADC dominates. 7 bits at full scale 3.0 × rms costs 0.25 / 0.60 dB
(Ch2 / Ch4) at the 1e-12 point; 6 bits ≥ 1.46 dB on Ch4. Penalties grow toward low BER because
quantization noise is fixed while channel noise shrinks. Below full scale ≈ peak/rms (2.06 /
2.89) the ADC clips the noiseless signal. 10-bit coefficients and 10-bit FFE output cost
≤ 0.04 dB. At 1e-12, Ch4 σ = 0.77 ADC LSB (quantization not well dithered), so those penalties
are MSE-based estimates; hardware measures them in Phase C.
